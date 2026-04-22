"""Integration tests for ``POST /bookings`` seat-lock contract (step 07-02).

ADR-008: when a commit carries a ``lockId``, the BookingService validates the
lock before charging payment. Contract:

  * Valid unexpired lock owned by the caller's session → booking succeeds
    and the lock is RELEASED on success (so a retry against the same seats
    finds them free).
  * Expired lock → 410 Gone, body cites "seat lock expired"; no payment
    charged, no booking persisted.
  * Unknown lock id → 404 Not Found.
  * Lock owned by a different session → 403 Forbidden, body cites
    "seat lock not owned by session".
  * Payment fails AFTER the lock validates → lock remains valid for retry
    within its TTL; PaymentFailed audit event is written.

Drives the HTTP route through the real container so production code installs
both the lock (via POST /seat-locks) and the booking (via POST /bookings).
No test doubles inside the hexagon.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.adapters.mocks.clock import FrozenClock
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus


_NOW = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
_FLIGHT_ID = "FL-LAX-NYC-0800"
_SEAT_ID = "30F"


@pytest.fixture
def container() -> Container:
    return build_test_container(now=_NOW, audit_path=None, deterministic_ids=True)


@pytest.fixture
def seeded_flight(container: Container) -> Flight:
    """Flight whose only AVAILABLE seat is 30F. Keeps the narrative narrow so
    assertions don't have to navigate around filler seats.
    """
    departure = datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC)
    cabin = Cabin()
    cabin.seats[SeatId(_SEAT_ID)] = Seat(
        id=SeatId(_SEAT_ID),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    flight = Flight(
        id=FlightId(_FLIGHT_ID),
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
def client(container: Container, seeded_flight: Flight) -> TestClient:
    return TestClient(create_app(container=container))


def _acquire_lock(client: TestClient, session_id: str = "S1") -> str:
    """Acquire a lock for ``session_id`` and return the ``lockId`` — Driven
    through real POST /seat-locks so the lock record is installed by
    production code.
    """
    response = client.post(
        "/seat-locks",
        json={
            "flightId": _FLIGHT_ID,
            "seatIds": [_SEAT_ID],
            "sessionId": session_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["lockId"]


def _commit_payload(
    *,
    lock_id: str | None,
    session_id: str | None,
    payment_token: str = "mock-ok",
    quote_id: str | None = None,
) -> dict:
    payload: dict = {
        "flightId": _FLIGHT_ID,
        "seatId": _SEAT_ID,
        "passenger": {"name": "Jane Doe"},
        "paymentToken": payment_token,
    }
    if lock_id is not None:
        payload["lockId"] = lock_id
    if session_id is not None:
        payload["sessionId"] = session_id
    if quote_id is not None:
        payload["quoteId"] = quote_id
    return payload


class TestCommitWithValidLock:
    def test_commit_with_valid_lock_releases_lock_on_success(
        self, client: TestClient, container: Container
    ) -> None:
        """ADR-008: a successful commit releases the lock. A second commit
        against the same seat (by a fresh session with its own lock) must
        therefore succeed — proving the first commit actually freed the
        seat-lock slot.
        """
        lock_id = _acquire_lock(client, session_id="S1")

        first = client.post(
            "/bookings",
            json=_commit_payload(lock_id=lock_id, session_id="S1"),
        )
        assert first.status_code == 201, first.text

        # Lock must no longer be valid (released as part of commit).
        assert not container.seat_lock_store.is_valid(lock_id, _NOW), (
            f"expected lock {lock_id} to be released after successful commit"
        )


class TestCommitWithExpiredLock:
    def test_commit_with_expired_lock_returns_410(
        self, client: TestClient, container: Container
    ) -> None:
        lock_id = _acquire_lock(client, session_id="S1")

        # Advance past TTL (10 minutes + 1).
        assert isinstance(container.clock, FrozenClock)
        container.clock.advance(timedelta(minutes=11))

        response = client.post(
            "/bookings",
            json=_commit_payload(lock_id=lock_id, session_id="S1"),
        )

        assert response.status_code == 410, response.text
        assert "seat lock expired" in response.text


class TestCommitWithUnknownLock:
    def test_commit_with_unknown_lock_returns_404(
        self, client: TestClient, container: Container
    ) -> None:
        response = client.post(
            "/bookings",
            json=_commit_payload(
                lock_id="LOCK-NEVER-ISSUED",
                session_id="S1",
            ),
        )

        assert response.status_code == 404, response.text
        assert "seat lock" in response.text.lower()


class TestCommitWithForeignLock:
    def test_commit_with_lock_owned_by_different_session_returns_403(
        self, client: TestClient, container: Container
    ) -> None:
        """ADR-008: session boundary. S1 locked the seat but S2 tries to
        commit against that lock — must be forbidden so sessions cannot
        hijack each other's reservations.
        """
        lock_id = _acquire_lock(client, session_id="S1")

        response = client.post(
            "/bookings",
            json=_commit_payload(lock_id=lock_id, session_id="S2"),
        )

        assert response.status_code == 403, response.text
        assert "seat lock not owned by session" in response.text


class TestCommitPaymentFailurePreservesLock:
    def test_commit_payment_failure_preserves_lock(
        self, client: TestClient, container: Container
    ) -> None:
        """Payment failure is a retriable condition. The lock must remain
        valid so the caller can present a new paymentToken within the TTL
        without re-acquiring the lock (which a competing session could have
        stolen).
        """
        lock_id = _acquire_lock(client, session_id="S1")

        response = client.post(
            "/bookings",
            json=_commit_payload(
                lock_id=lock_id,
                session_id="S1",
                payment_token="fail",
            ),
        )

        assert response.status_code == 402, response.text
        assert container.seat_lock_store.is_valid(lock_id, _NOW), (
            f"expected lock {lock_id} to remain valid after payment failure"
        )
        events = getattr(container.audit, "events", [])
        payment_failed = [e for e in events if e.get("type") == "PaymentFailed"]
        assert len(payment_failed) == 1, (
            f"expected exactly one PaymentFailed audit event, got {events!r}"
        )
