"""InMemorySeatLockStore.

ADR-008: ``acquire`` runs under the store's own RLock so the check-then-install
sequence is atomic with respect to concurrent callers. Expired lock records
are treated as free on the next ``acquire`` — no sweeper thread in this slice;
phase 07-02/03 may add one if operational data demands it.

State is tracked by two dicts: ``_by_seat`` (for fast conflict lookup) and
``_by_lock`` (reverse lookup for ``release``/``is_valid``). A single lock can
cover multiple seats; both dicts point at the same ``LockRecord`` instance so
freshness is a single source of truth.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from flights.domain.model.ids import FlightId, SeatId, SessionId

LOCK_TTL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class LockRecord:
    lock_id: str
    flight_id: FlightId
    seat_ids: tuple[SeatId, ...]
    session_id: SessionId
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SeatLock:
    lock_id: str
    flight_id: FlightId
    seat_ids: tuple[SeatId, ...]
    session_id: SessionId
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class SeatLockConflict:
    conflicting_seats: tuple[SeatId, ...]


def _default_lock_id() -> str:
    return uuid.uuid4().hex


class InMemorySeatLockStore:
    """Coarse-grained in-memory seat-lock store.

    ``ids`` is a zero-arg callable returning the next lock id to issue.
    Acceptance tests inject a deterministic sequence via
    ``DeterministicIdGenerator.new_lock_id``; unit tests pass a simple
    list-popping callable; production uses the uuid4-hex default.
    """

    def __init__(self, ids: Callable[[], str] | None = None) -> None:
        self._by_seat: dict[SeatId, LockRecord] = {}
        self._by_lock: dict[str, LockRecord] = {}
        self._lock = threading.RLock()
        self._ids: Callable[[], str] = ids or _default_lock_id

    def acquire(
        self,
        flight_id: FlightId,
        seat_ids: tuple[SeatId, ...],
        session_id: SessionId,
        now: datetime,
    ) -> SeatLock | SeatLockConflict:
        """Atomic check-then-install under the store's RLock.

        Returns a :class:`SeatLock` if every target seat is free (no record
        at all, or an expired record, or a record owned by ``session_id``).
        Returns :class:`SeatLockConflict` listing the offending seats if any
        is locked by a different live session — no partial install.
        """
        with self._lock:
            conflicts = self._find_conflicts(seat_ids, session_id, now)
            if conflicts:
                return SeatLockConflict(conflicts)
            return self._install_lock(flight_id, seat_ids, session_id, now)

    def release(self, lock_id: str) -> None:
        """Purge the lock record and every seat it covers.

        Idempotent: unknown ids are a no-op so concurrent releasers never
        raise. This keeps the caller's happy path unconditional.
        """
        with self._lock:
            record = self._by_lock.pop(lock_id, None)
            if record is None:
                return
            for seat_id in record.seat_ids:
                current = self._by_seat.get(seat_id)
                if current is not None and current.lock_id == record.lock_id:
                    self._by_seat.pop(seat_id, None)

    def is_valid(self, lock_id: str, now: datetime) -> bool:
        """True iff the lock exists and ``now < expires_at``.

        Uses a strict ``<`` so the exact ``expires_at`` instant is expired —
        matches the half-open TTL window used by the quote store and keeps
        the boundary test deterministic.
        """
        with self._lock:
            record = self._by_lock.get(lock_id)
            if record is None:
                return False
            return now < record.expires_at

    # --- private helpers -----------------------------------------------------

    def _find_conflicts(
        self,
        seat_ids: tuple[SeatId, ...],
        session_id: SessionId,
        now: datetime,
    ) -> tuple[SeatId, ...]:
        conflicts: list[SeatId] = []
        for seat_id in seat_ids:
            record = self._by_seat.get(seat_id)
            if record is None:
                continue
            if record.expires_at <= now:
                continue
            if record.session_id == session_id:
                continue
            conflicts.append(seat_id)
        return tuple(conflicts)

    def _install_lock(
        self,
        flight_id: FlightId,
        seat_ids: tuple[SeatId, ...],
        session_id: SessionId,
        now: datetime,
    ) -> SeatLock:
        lock_id = self._ids()
        expires_at = now + LOCK_TTL
        record = LockRecord(
            lock_id=lock_id,
            flight_id=flight_id,
            seat_ids=tuple(seat_ids),
            session_id=session_id,
            expires_at=expires_at,
        )
        self._by_lock[lock_id] = record
        for seat_id in seat_ids:
            self._by_seat[seat_id] = record
        return SeatLock(
            lock_id=lock_id,
            flight_id=flight_id,
            seat_ids=tuple(seat_ids),
            session_id=session_id,
            expires_at=expires_at,
        )

    # --- internal query used by SeatMapService (package-private) ------------

    def find_active_lock_for_seat(
        self, seat_id: SeatId, now: datetime,
    ) -> LockRecord | None:
        """Return the live lock record on ``seat_id`` at time ``now``, or
        ``None`` if there is no record or the record has expired.

        The SeatMapService uses this to mark seats OCCUPIED to sessions
        other than the lock-holder. It is deliberately not on the driven
        port because the port surface is session-agnostic; the method is
        an internal helper that avoids leaking ``_by_seat`` / ``_by_lock``.
        """
        with self._lock:
            record = self._by_seat.get(seat_id)
            if record is None:
                return None
            if record.expires_at <= now:
                return None
            return record
