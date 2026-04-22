"""SeatMapService.

Composes ``Flight.cabin`` + ``BookingRepository`` + ``SeatLockStore`` state
to compute the per-seat status presented by ``GET /flights/{id}/seats``:

- ``BLOCKED`` if the seat's cabin status is BLOCKED.
- ``OCCUPIED`` if any CONFIRMED booking on that flight claims the seat.
- ``OCCUPIED`` if another session holds a valid seat lock on it (step 07-01).
  The lock-holder sees their own seat as AVAILABLE so they can complete the
  booking flow they started.
- ``AVAILABLE`` otherwise.

``session_id`` is optional: if ``None``, any live lock marks the seat as
OCCUPIED (conservative — matches existing milestone-03 scenarios that do
not identify the requester). If a ``session_id`` is supplied, a lock owned
by that same session is transparent.
"""

from __future__ import annotations

from dataclasses import dataclass

from flights.adapters.inmemory.seat_lock_store import InMemorySeatLockStore
from flights.domain.model.booking import BookingStatus
from flights.domain.model.flight import Flight
from flights.domain.model.ids import FlightId, SeatId, SessionId
from flights.domain.model.seat import SeatClass, SeatKind, SeatStatus
from flights.domain.ports import BookingRepository, Clock, FlightRepository, SeatLockStore


@dataclass(frozen=True, slots=True)
class SeatMapEntry:
    seat_id: SeatId
    seat_class: SeatClass
    kind: SeatKind
    status: SeatStatus


def _row_column(seat_id: SeatId) -> tuple[int, str]:
    """Split a seat id like ``12C`` into ``(12, "C")`` for deterministic sorting.

    Falls back to ``(0, value)`` for non-standard ids so sorting remains total.
    """
    text = seat_id.value
    digits: list[str] = []
    i = 0
    while i < len(text) and text[i].isdigit():
        digits.append(text[i])
        i += 1
    if not digits:
        return (0, text)
    return (int("".join(digits)), text[i:])


class SeatMapService:
    def __init__(
        self,
        flights: FlightRepository,
        bookings: BookingRepository,
        locks: SeatLockStore,
        clock: Clock,
    ) -> None:
        self._flights = flights
        self._bookings = bookings
        self._locks = locks
        self._clock = clock

    def view(
        self,
        flight_id: FlightId,
        session_id: SessionId | None = None,
    ) -> tuple[SeatMapEntry, ...] | None:
        """Return a row/column-ordered seat map for the flight, or ``None``
        if the flight is unknown. The HTTP adapter maps ``None`` to 404.

        When ``session_id`` is provided, seats held by a valid lock owned by
        a different session are reported OCCUPIED; the lock-holder's own
        seats remain AVAILABLE so the traveller can complete the commit flow
        they initiated.
        """
        flight = self._flights.get(flight_id)
        if flight is None:
            return None
        occupied_ids = self._occupied_seat_ids(flight_id)
        locked_to_other = self._seats_locked_against_session(flight, session_id)
        return tuple(
            SeatMapEntry(
                seat_id=seat.id,
                seat_class=seat.seat_class,
                kind=seat.kind,
                status=self._status_for(
                    seat.status,
                    seat.id,
                    occupied_ids,
                    locked_to_other,
                ),
            )
            for seat in self._ordered_seats(flight)
        )

    def _occupied_seat_ids(self, flight_id: FlightId) -> frozenset[SeatId]:
        occupied: set[SeatId] = set()
        for booking in self._bookings.iter_all():
            if booking.flight_id != flight_id:
                continue
            if booking.status != BookingStatus.CONFIRMED:
                continue
            occupied.update(booking.seat_ids)
        return frozenset(occupied)

    def _seats_locked_against_session(
        self,
        flight: Flight,
        session_id: SessionId | None,
    ) -> frozenset[SeatId]:
        """Return the set of seats the requester must see as OCCUPIED because
        a *different* session holds a live lock on them.

        The lock store's public Protocol surface is session-agnostic so we
        reach for an internal helper exposed on ``InMemorySeatLockStore``
        (``find_active_lock_for_seat``). This is safe because the composition
        root wires exactly this concrete type; non-InMemory adapters would
        add a matching helper or extend the Port.
        """
        store = self._locks
        if not isinstance(store, InMemorySeatLockStore):
            return frozenset()
        now = self._clock.now()
        against: set[SeatId] = set()
        for seat_id in flight.cabin.seats:
            record = store.find_active_lock_for_seat(seat_id, now)
            if record is None:
                continue
            if session_id is not None and record.session_id == session_id:
                continue
            against.add(seat_id)
        return frozenset(against)

    @staticmethod
    def _status_for(
        cabin_status: SeatStatus,
        seat_id: SeatId,
        occupied_ids: frozenset[SeatId],
        locked_to_other: frozenset[SeatId],
    ) -> SeatStatus:
        if cabin_status == SeatStatus.BLOCKED:
            return SeatStatus.BLOCKED
        if seat_id in occupied_ids:
            return SeatStatus.OCCUPIED
        if seat_id in locked_to_other:
            return SeatStatus.OCCUPIED
        return SeatStatus.AVAILABLE

    @staticmethod
    def _ordered_seats(flight: Flight) -> tuple:
        return tuple(sorted(flight.cabin.seats.values(), key=lambda seat: _row_column(seat.id)))
