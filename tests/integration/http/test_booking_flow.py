"""Integration tests for the HTTP driving adapter wired to the real container.

These tests exercise the FastAPI app end-to-end through TestClient against
the test container built by ``build_test_container``. They are narrower than
the walking-skeleton BDD scenario (focused on HTTP contract and the happy
path for each route) but share the same real-adapter wiring.

Scope for step 01-03: search, book, retrieve and a 404 for an unknown
booking reference. Quote/lock/cancellation/payment-failure branches come in
later phases.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind


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
        cabin=Cabin(),
    )
    seat = Seat(id=SeatId("12C"), seat_class=SeatClass.ECONOMY, kind=SeatKind.STANDARD)
    flight.cabin.seats[seat.id] = seat
    container.flight_repo.add(flight)
    return flight


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container=container))


class TestSearchEndpoint:
    def test_search_endpoint_returns_seeded_flight(
        self, client: TestClient, seeded_flight: Flight
    ) -> None:
        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
            },
        )

        assert response.status_code == 200
        body = response.json()
        flight_ids = [f.get("id") or f.get("flightId") for f in body["flights"]]
        assert "FL-LAX-NYC-0800" in flight_ids


class TestBookingCreationEndpoint:
    def test_booking_endpoint_creates_confirmed_booking(
        self, client: TestClient, seeded_flight: Flight
    ) -> None:
        response = client.post(
            "/bookings",
            json={
                "flightId": "FL-LAX-NYC-0800",
                "seatId": "12C",
                "passenger": {"name": "Jane Doe"},
                "paymentToken": "mock-ok",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "CONFIRMED"
        assert body["bookingReference"]
        assert body["flightId"] == "FL-LAX-NYC-0800"
        assert "12C" in body["seats"]


class TestGetBookingEndpoint:
    def test_get_booking_endpoint_returns_booking_state(
        self, client: TestClient, seeded_flight: Flight
    ) -> None:
        create = client.post(
            "/bookings",
            json={
                "flightId": "FL-LAX-NYC-0800",
                "seatId": "12C",
                "passenger": {"name": "Jane Doe"},
                "paymentToken": "mock-ok",
            },
        )
        reference = create.json()["bookingReference"]

        response = client.get(f"/bookings/{reference}")

        assert response.status_code == 200
        body = response.json()
        assert body["bookingReference"] == reference
        assert body["status"] == "CONFIRMED"
        assert body["flightId"] == "FL-LAX-NYC-0800"
        assert "12C" in body["seats"]

    def test_unknown_booking_returns_404(self, client: TestClient) -> None:
        response = client.get("/bookings/DOES-NOT-EXIST")

        assert response.status_code == 404
