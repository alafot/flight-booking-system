"""Integration tests for the seat-map HTTP route.

Step 03-02 — seat-map endpoint now composes Flight + Bookings so that seat
status reflects the current state (AVAILABLE / OCCUPIED / BLOCKED). Tests
exercise the FastAPI app through TestClient against a real wired container
and assert at the HTTP response boundary (port-to-port: driving HTTP port,
driven in-memory repositories mutated via production code only).

Lock-derived OCCUPIED-to-other-sessions is Phase 07; not tested here.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import SeatStatus
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


class TestSeatMapNotFound:
    def test_seat_map_for_unseeded_flight_returns_404(self, client: TestClient) -> None:
        response = client.get("/flights/FL-UNKNOWN/seats")

        assert response.status_code == 404
        body = response.json()
        assert "flight not found" in body.get("detail", "").lower()


class TestSeatMapContents:
    def test_seat_map_returns_180_seats_with_status_available(
        self, client: TestClient, seeded_flight: Flight
    ) -> None:
        response = client.get(f"/flights/{seeded_flight.id.value}/seats")

        assert response.status_code == 200
        body = response.json()
        seats = body.get("seats", [])
        assert len(seats) == 180, f"expected 180 seats, got {len(seats)}"
        # Every seat in the default cabin starts AVAILABLE (no bookings, no blocks).
        statuses = {s.get("status") for s in seats}
        assert statuses == {"AVAILABLE"}, f"expected all AVAILABLE, got {statuses}"
        # Each entry exposes the full contract.
        sample = seats[0]
        assert set(sample.keys()) >= {"seatId", "class", "kind", "status"}

    def test_seat_map_marks_booked_seat_occupied(
        self, client: TestClient, seeded_flight: Flight
    ) -> None:
        # Exercise the production booking path so the seat-map view must
        # consult the booking repository — no direct repo mutation.
        book_response = client.post(
            "/bookings",
            json={
                "flightId": seeded_flight.id.value,
                "seatId": "12C",
                "passenger": {"name": "Jane Doe"},
                "paymentToken": "mock-ok",
            },
        )
        assert book_response.status_code == 201

        response = client.get(f"/flights/{seeded_flight.id.value}/seats")

        assert response.status_code == 200
        seats = response.json()["seats"]
        booked = next(s for s in seats if s["seatId"] == "12C")
        assert booked["status"] == "OCCUPIED"
        # Adjacent seats stay AVAILABLE — no accidental over-occupation.
        neighbor = next(s for s in seats if s["seatId"] == "12D")
        assert neighbor["status"] == "AVAILABLE"

    def test_seat_map_marks_blocked_seat_blocked(
        self, container: Container, client: TestClient, seeded_flight: Flight
    ) -> None:
        # Synthesize a BLOCKED seat by mutating the cabin fixture: Seat is frozen,
        # so we replace it with a BLOCKED variant at the same id.
        blocked_id = SeatId("14A")
        original = seeded_flight.cabin.seats[blocked_id]
        seeded_flight.cabin.seats[blocked_id] = replace(original, status=SeatStatus.BLOCKED)

        response = client.get(f"/flights/{seeded_flight.id.value}/seats")

        assert response.status_code == 200
        seats = response.json()["seats"]
        blocked = next(s for s in seats if s["seatId"] == "14A")
        assert blocked["status"] == "BLOCKED"
