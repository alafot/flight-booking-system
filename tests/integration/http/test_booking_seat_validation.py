"""Integration tests for seat validation on commit (step 03-03).

Exercises POST /bookings through the FastAPI driving adapter wired to the
real container. Validates that the seat-identity / seat-status checks run
BEFORE payment is charged and map to the correct HTTP status codes.

Port-to-port: tests enter through the HTTP driving port and assert on the
HTTP response (the observable outcome). The internal ``BookingService``
and ``CommitResult`` error codes are implementation details asserted
indirectly through the response status and body.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.booking import Booking, BookingStatus
from flights.domain.model.flight import Flight
from flights.domain.model.ids import BookingReference, FlightId, QuoteId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.passenger import PassengerDetails
from flights.domain.model.seat import Seat, SeatStatus
from tests.fixtures.cabin import default_cabin


@pytest.fixture
def container() -> Container:
    now = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
    return build_test_container(now=now, audit_path=None, deterministic_ids=True)


@pytest.fixture
def seeded_flight(container: Container) -> Flight:
    departure = datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC)
    flight = Flight(
        id=FlightId("FL-LAX-NYC-0800"),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of("299"),
        cabin=default_cabin(),
    )
    container.flight_repo.add(flight)
    return flight


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container=container))


def _booking_payload(seat_id: str) -> dict:
    return {
        "flightId": "FL-LAX-NYC-0800",
        "seatId": seat_id,
        "passenger": {"name": "Jane Doe"},
        "paymentToken": "mock-ok",
    }


class TestUnknownSeat:
    def test_booking_unknown_seat_returns_400_unknown_seat(
        self, client: TestClient, seeded_flight: Flight
    ) -> None:
        response = client.post("/bookings", json=_booking_payload("99Z"))

        assert response.status_code == 400
        assert "unknown seat" in response.text


class TestOccupiedSeat:
    def test_booking_occupied_seat_returns_409_already_booked(
        self,
        client: TestClient,
        seeded_flight: Flight,
        container: Container,
    ) -> None:
        # Seat 12C belongs to the default cabin and is AVAILABLE; record a
        # prior CONFIRMED booking that already covers it.
        existing = Booking(
            reference=BookingReference("BK-PREEXISTING"),
            flight_id=FlightId("FL-LAX-NYC-0800"),
            seat_ids=(SeatId("12C"),),
            passengers=(PassengerDetails(full_name="Previous Passenger"),),
            total_charged=Money.of("299"),
            status=BookingStatus.CONFIRMED,
            quote_id=QuoteId("Q-PREEXISTING"),
            confirmed_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
        )
        container.booking_repo.save(existing)

        response = client.post("/bookings", json=_booking_payload("12C"))

        assert response.status_code == 409
        assert "seat already booked" in response.text


class TestBlockedSeat:
    def test_booking_blocked_seat_returns_409_not_for_sale(
        self,
        client: TestClient,
        seeded_flight: Flight,
    ) -> None:
        # Mutate the cabin so 14A is BLOCKED for maintenance.
        existing = seeded_flight.cabin.seats[SeatId("14A")]
        seeded_flight.cabin.seats[existing.id] = Seat(
            id=existing.id,
            seat_class=existing.seat_class,
            kind=existing.kind,
            status=SeatStatus.BLOCKED,
        )

        response = client.post("/bookings", json=_booking_payload("14A"))

        assert response.status_code == 409
        assert "seat not for sale" in response.text
