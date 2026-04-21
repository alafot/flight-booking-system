"""SeatMapService.

Composes ``Flight.cabin`` + ``BookingRepository`` state to compute the
per-seat status presented by ``GET /flights/{id}/seats``:

- ``BLOCKED`` if the seat's cabin status is BLOCKED.
- ``OCCUPIED`` if any CONFIRMED booking on that flight claims the seat.
- ``AVAILABLE`` otherwise.

Lock-derived OCCUPIED-to-other-sessions is Phase 07 and deliberately
not computed here. The ``locks`` port and ``clock`` remain on the
constructor for forward-compatibility but are unused this phase.
"""

from __future__ import annotations

from dataclasses import dataclass

from flights.domain.model.booking import BookingStatus
from flights.domain.model.flight import Flight
from flights.domain.model.ids import FlightId, SeatId
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

    def view(self, flight_id: FlightId) -> tuple[SeatMapEntry, ...] | None:
        """Return a row/column-ordered seat map for the flight, or ``None``
        if the flight is unknown. The HTTP adapter maps ``None`` to 404.
        """
        flight = self._flights.get(flight_id)
        if flight is None:
            return None
        occupied_ids = self._occupied_seat_ids(flight_id)
        return tuple(
            SeatMapEntry(
                seat_id=seat.id,
                seat_class=seat.seat_class,
                kind=seat.kind,
                status=self._status_for(seat.status, seat.id, occupied_ids),
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

    @staticmethod
    def _status_for(
        cabin_status: SeatStatus,
        seat_id: SeatId,
        occupied_ids: frozenset[SeatId],
    ) -> SeatStatus:
        if cabin_status == SeatStatus.BLOCKED:
            return SeatStatus.BLOCKED
        if seat_id in occupied_ids:
            return SeatStatus.OCCUPIED
        return SeatStatus.AVAILABLE

    @staticmethod
    def _ordered_seats(flight: Flight) -> tuple:
        return tuple(
            sorted(flight.cabin.seats.values(), key=lambda seat: _row_column(seat.id))
        )
