"""Integration tests for the ``POST /seat-locks`` HTTP route (step 07-01).

Exercised through the FastAPI TestClient against the real ``build_test_container``.
Port-to-port: driving HTTP port → application service (SeatHoldService) →
driven SeatLockStore. No test doubles inside the hexagon.

Coverage:
  * 201 on a free seat; body carries lockId + ISO expiresAt 10 minutes out.
  * 409 with conflicting-seats list when another session holds a valid lock.
  * GET /flights/{id}/seats?sessionId=... reports locked seats OCCUPIED to
    the other session (seat-map extension in the same slice).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus


_NOW = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def container() -> Container:
    return build_test_container(now=_NOW, audit_path=None, deterministic_ids=True)


@pytest.fixture
def seeded_flight(container: Container) -> Flight:
    """A minimal flight whose cabin has one AVAILABLE seat (30F). The lock
    endpoint does not validate that seats belong to the flight in this
    slice — the integration tests only exercise the lock state machine.
    """
    departure = datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC)
    cabin = Cabin()
    cabin.seats[SeatId("30F")] = Seat(
        id=SeatId("30F"),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    flight = Flight(
        id=FlightId("FL-LAX-NYC-0800"),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of("299"),
        cabin=cabin,
    )
    container.flight_repo.add(flight)
    return flight


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container=container))


class TestSeatLockAcquire:
    def test_post_seat_lock_returns_201_for_free_seat(
        self, client: TestClient, seeded_flight: Flight,
    ) -> None:
        response = client.post(
            "/seat-locks",
            json={
                "flightId": seeded_flight.id.value,
                "seatIds": ["30F"],
                "sessionId": "S1",
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body.get("lockId"), f"missing lockId: {body!r}"
        # expiresAt is ISO-8601 exactly 10 minutes after the frozen clock.
        expires_at = datetime.fromisoformat(body["expiresAt"])
        assert expires_at == _NOW + timedelta(minutes=10)

    def test_post_seat_lock_returns_409_for_locked_seat_from_other_session(
        self, client: TestClient, seeded_flight: Flight,
    ) -> None:
        # S1 takes the lock first.
        first = client.post(
            "/seat-locks",
            json={
                "flightId": seeded_flight.id.value,
                "seatIds": ["30F"],
                "sessionId": "S1",
            },
        )
        assert first.status_code == 201, first.text

        # S2 hits the same seat — must observe a 409 with the conflict.
        second = client.post(
            "/seat-locks",
            json={
                "flightId": seeded_flight.id.value,
                "seatIds": ["30F"],
                "sessionId": "S2",
            },
        )

        assert second.status_code == 409, second.text
        body = second.json()
        assert "seat unavailable" in body.get("detail", "").lower(), body
        assert body.get("conflicts") == ["30F"], body


class TestSeatMapWithActiveLock:
    def test_seat_map_shows_locked_seat_as_unavailable_to_other_session(
        self, client: TestClient, seeded_flight: Flight,
    ) -> None:
        # S1 locks the seat.
        first = client.post(
            "/seat-locks",
            json={
                "flightId": seeded_flight.id.value,
                "seatIds": ["30F"],
                "sessionId": "S1",
            },
        )
        assert first.status_code == 201, first.text

        # S2 queries the seat map with their session id — sees 30F OCCUPIED.
        map_response = client.get(
            f"/flights/{seeded_flight.id.value}/seats",
            params={"sessionId": "S2"},
        )
        assert map_response.status_code == 200, map_response.text
        seats = map_response.json()["seats"]
        locked_entry = next(s for s in seats if s["seatId"] == "30F")
        assert locked_entry["status"] == "OCCUPIED", locked_entry

        # The lock holder sees their own seat as AVAILABLE still.
        own_view = client.get(
            f"/flights/{seeded_flight.id.value}/seats",
            params={"sessionId": "S1"},
        )
        assert own_view.status_code == 200, own_view.text
        own_entry = next(s for s in own_view.json()["seats"] if s["seatId"] == "30F")
        assert own_entry["status"] == "AVAILABLE", own_entry
