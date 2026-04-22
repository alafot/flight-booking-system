"""InMemorySeatLockStore — unit tests (step 07-01).

Port-to-port at driven-port scope: tests invoke the store's public Protocol
surface (``acquire``, ``release``, ``is_valid``) with a callable-based id
generator and assert on return types + observable state transitions. No
internal fields are inspected.

ADR-008: ``acquire`` runs under the store's RLock; the whole check-then-install
sequence is atomic. Expired locks are treated as free on the next acquire.
The TTL is pinned at 10 minutes (``LOCK_TTL``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flights.adapters.inmemory.seat_lock_store import (
    LOCK_TTL,
    InMemorySeatLockStore,
    SeatLock,
    SeatLockConflict,
)
from flights.domain.model.ids import FlightId, SeatId, SessionId


_NOW = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
_FLIGHT = FlightId("FL-LAX-NYC-0800")


def _seq_ids(*values: str):
    """Build a simple id generator as an iterator — the store accepts any
    zero-arg callable so this keeps the test free of adapter coupling.
    """
    queue = list(values)

    def _next() -> str:
        return queue.pop(0)

    return _next


class TestAcquireInstallsLock:
    def test_acquire_free_seat_succeeds(self) -> None:
        store = InMemorySeatLockStore(ids=_seq_ids("L1"))

        result = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S1"),
            now=_NOW,
        )

        assert isinstance(result, SeatLock)
        assert result.lock_id == "L1"
        assert result.flight_id == _FLIGHT
        assert result.seat_ids == (SeatId("30F"),)
        assert result.session_id == SessionId("S1")
        assert result.expires_at == _NOW + LOCK_TTL


class TestAcquireIdempotentForSameSession:
    def test_acquire_owned_by_same_session_is_idempotent(self) -> None:
        """Re-acquiring from the same session must succeed — installs a new
        lock record and frees any seats it may have covered that no longer
        belong. This is the "same session sees its own lock as free" branch.
        """
        store = InMemorySeatLockStore(ids=_seq_ids("L1", "L2"))
        first = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S1"),
            now=_NOW,
        )
        assert isinstance(first, SeatLock)

        second = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S1"),
            now=_NOW,
        )

        assert isinstance(second, SeatLock)
        assert second.session_id == SessionId("S1")


class TestAcquireConflict:
    def test_acquire_owned_by_other_session_returns_conflict(self) -> None:
        store = InMemorySeatLockStore(ids=_seq_ids("L1", "L2"))
        first = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S1"),
            now=_NOW,
        )
        assert isinstance(first, SeatLock)

        second = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S2"),
            now=_NOW,
        )

        assert isinstance(second, SeatLockConflict)
        assert second.conflicting_seats == (SeatId("30F"),)
        # S1's lock is still valid — no partial install on conflict.
        assert store.is_valid(first.lock_id, _NOW) is True


class TestExpiredLockTreatedAsFree:
    def test_expired_lock_treated_as_free_on_next_acquire(self) -> None:
        store = InMemorySeatLockStore(ids=_seq_ids("L1", "L2"))
        first = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S1"),
            now=_NOW,
        )
        assert isinstance(first, SeatLock)

        # One second past the TTL the lock is expired — a different session
        # can now acquire cleanly.
        later = _NOW + LOCK_TTL + timedelta(seconds=1)
        second = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S2"),
            now=later,
        )

        assert isinstance(second, SeatLock)
        assert second.session_id == SessionId("S2")


class TestRelease:
    def test_release_frees_all_seats_of_the_lock(self) -> None:
        """A single lock can cover multiple seats — release must purge every
        one of them from the store so subsequent acquires succeed cleanly.
        """
        store = InMemorySeatLockStore(ids=_seq_ids("L1", "L2"))
        first = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"), SeatId("30G")),
            session_id=SessionId("S1"),
            now=_NOW,
        )
        assert isinstance(first, SeatLock)

        store.release(first.lock_id)

        # Another session can now acquire BOTH seats — nothing residual.
        second = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"), SeatId("30G")),
            session_id=SessionId("S2"),
            now=_NOW,
        )
        assert isinstance(second, SeatLock)
        # And the released lock id is no longer valid.
        assert store.is_valid(first.lock_id, _NOW) is False


class TestIsValid:
    def test_is_valid_returns_true_before_expiry(self) -> None:
        store = InMemorySeatLockStore(ids=_seq_ids("L1"))
        lock = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S1"),
            now=_NOW,
        )
        assert isinstance(lock, SeatLock)

        # One microsecond before expires_at is still valid.
        just_before = lock.expires_at - timedelta(microseconds=1)
        assert store.is_valid(lock.lock_id, just_before) is True

    def test_is_valid_returns_false_at_or_after_expiry(self) -> None:
        store = InMemorySeatLockStore(ids=_seq_ids("L1"))
        lock = store.acquire(
            flight_id=_FLIGHT,
            seat_ids=(SeatId("30F"),),
            session_id=SessionId("S1"),
            now=_NOW,
        )
        assert isinstance(lock, SeatLock)

        # At the exact expires_at instant: expired (half-open window).
        assert store.is_valid(lock.lock_id, lock.expires_at) is False
        # And any later instant.
        assert store.is_valid(lock.lock_id, lock.expires_at + timedelta(seconds=1)) is False

    def test_is_valid_returns_false_for_unknown_lock_id(self) -> None:
        store = InMemorySeatLockStore(ids=_seq_ids())
        assert store.is_valid("DOES-NOT-EXIST", _NOW) is False
