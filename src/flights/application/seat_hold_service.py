"""SeatHoldService.

Application service driving the seat-lock primitive. Thin delegator over
:class:`SeatLockStore`: injects the current clock instant and wraps the
store's union return (``SeatLock`` | ``SeatLockConflict``) into a flat
``SeatHoldResult`` the HTTP adapter can project onto wire fields without
having to know the domain's sum type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from flights.adapters.inmemory.seat_lock_store import SeatLock, SeatLockConflict
from flights.domain.model.ids import FlightId, SeatId, SessionId
from flights.domain.ports import Clock, SeatLockStore


@dataclass(frozen=True, slots=True)
class SeatHoldResult:
    success: bool
    lock_id: str | None = None
    expires_at: datetime | None = None
    conflicts: tuple[SeatId, ...] = field(default_factory=tuple)


class SeatHoldService:
    def __init__(self, locks: SeatLockStore, clock: Clock) -> None:
        self._locks = locks
        self._clock = clock

    def acquire(
        self,
        flight_id: FlightId,
        seat_ids: tuple[SeatId, ...],
        session_id: SessionId,
    ) -> SeatHoldResult:
        """Delegate to the store with the injected clock.

        Returns :class:`SeatHoldResult` with ``success=True`` + ``lock_id`` +
        ``expires_at`` on acquisition, or ``success=False`` + ``conflicts`` on
        conflict. The HTTP adapter maps ``success`` to 201/409 and serialises
        the remaining fields directly onto the wire response body.
        """
        outcome = self._locks.acquire(
            flight_id=flight_id,
            seat_ids=seat_ids,
            session_id=session_id,
            now=self._clock.now(),
        )
        if isinstance(outcome, SeatLock):
            return SeatHoldResult(
                success=True,
                lock_id=outcome.lock_id,
                expires_at=outcome.expires_at,
            )
        if isinstance(outcome, SeatLockConflict):
            return SeatHoldResult(
                success=False,
                conflicts=outcome.conflicting_seats,
            )
        raise AssertionError(
            f"SeatLockStore.acquire returned unexpected type: {type(outcome).__name__}"
        )
