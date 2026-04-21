"""Flight + Cabin (scaffold)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat

__SCAFFOLD__ = True


class RouteKind(StrEnum):
    """Tax jurisdiction classification for a route (step 05-02).

    Two flat rates this iteration (ADR-007): DOMESTIC vs INTERNATIONAL. The
    distinction drives ``TAX_RATES`` selection in ``pricing.compute_taxes``.
    Per-jurisdiction rates are deferred — out of scope per the step brief.
    """

    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"


@dataclass
class Cabin:
    seats: dict[SeatId, Seat] = field(default_factory=dict)

    def seat_count(self) -> int:
        return len(self.seats)


@dataclass
class Flight:
    id: FlightId
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    airline: str
    base_fare: Money
    cabin: Cabin
    # Default DOMESTIC so existing fixtures continue to compile unchanged —
    # step 05-02 only extends the catalog to mark a few routes INTERNATIONAL.
    route_kind: RouteKind = RouteKind.DOMESTIC

    def duration_minutes(self) -> int:
        raise AssertionError("Not yet implemented — RED scaffold (Flight.duration_minutes)")

    def is_within_two_hours_of_departure(self, now: datetime) -> bool:
        raise AssertionError("Not yet implemented — RED scaffold (Flight.is_within_two_hours_of_departure)")
