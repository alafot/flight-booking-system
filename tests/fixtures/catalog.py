"""Deterministic seeded catalog for acceptance and unit tests.

``seeded_catalog()`` produces a reproducible list of :class:`Flight` objects
suitable for exercising the catalog search endpoint. Reproducibility is
achieved by deterministic enumeration of (route, date, airline) tuples — no
``random`` calls anywhere.

Coverage (per AC1 of step 02-01):

* ≥200 flights
* ≥20 routes
* ≥5 airlines
* ≥30 departure dates (2026-06-01..2026-06-30)
* 3 cabin classes (Economy, Business, First — at least one seat of each per flight)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind

ORIGINS: tuple[str, ...] = ("LAX", "JFK", "SFO", "ORD", "DFW")
DESTINATIONS: tuple[str, ...] = ("NYC", "LAX", "SEA", "MIA", "BOS")
AIRLINES: tuple[str, ...] = ("AA", "UA", "DL", "WN", "AS")
CATALOG_START_DATE = datetime(2026, 6, 1, tzinfo=UTC)
CATALOG_DAYS = 30
BASE_FARE_USD = "299"
FLIGHT_DURATION_HOURS = 5


def _routes() -> list[tuple[str, str]]:
    """Every origin × destination pair, excluding self-pairs.

    With 5 origins and 5 destinations (one overlap on ``LAX``) we yield 24
    distinct routes — more than the ≥20 AC requires.
    """
    return [
        (origin, destination)
        for origin in ORIGINS
        for destination in DESTINATIONS
        if origin != destination
    ]


def _seed_cabin() -> Cabin:
    """A minimal cabin with one seat per class — ensures all 3 classes appear."""
    cabin = Cabin()
    cabin.seats[SeatId("1A")] = Seat(
        id=SeatId("1A"), seat_class=SeatClass.FIRST, kind=SeatKind.WINDOW_SUITE
    )
    cabin.seats[SeatId("5B")] = Seat(
        id=SeatId("5B"), seat_class=SeatClass.BUSINESS, kind=SeatKind.STANDARD
    )
    cabin.seats[SeatId("20C")] = Seat(
        id=SeatId("20C"), seat_class=SeatClass.ECONOMY, kind=SeatKind.AISLE
    )
    return cabin


def seeded_catalog() -> list[Flight]:
    """Return a reproducible catalog of ≥200 flights.

    Two calls to this function return lists that are equal element-wise
    (same ids, same routes, same departure timestamps) — no randomness is used.
    """
    flights: list[Flight] = []
    routes = _routes()
    base_fare = Money.of(BASE_FARE_USD)
    for route_index, (origin, destination) in enumerate(routes):
        for day_offset in range(CATALOG_DAYS):
            departure_date = CATALOG_START_DATE + timedelta(days=day_offset)
            # Depart at 08:00 UTC to match the WS hour convention.
            departure_at = departure_date.replace(hour=8)
            arrival_at = departure_at + timedelta(hours=FLIGHT_DURATION_HOURS)
            airline = AIRLINES[(route_index + day_offset) % len(AIRLINES)]
            date_iso = departure_date.date().isoformat()
            flight_id = f"FL-{origin}-{destination}-{date_iso}-{airline}"
            flights.append(
                Flight(
                    id=FlightId(flight_id),
                    origin=origin,
                    destination=destination,
                    departure_at=departure_at,
                    arrival_at=arrival_at,
                    airline=airline,
                    base_fare=base_fare,
                    cabin=_seed_cabin(),
                )
            )
    return flights
