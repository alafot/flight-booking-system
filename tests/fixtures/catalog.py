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

from flights.domain.model.flight import Cabin, Flight, RouteKind
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind

ORIGINS: tuple[str, ...] = ("LAX", "JFK", "SFO", "ORD", "DFW")
DESTINATIONS: tuple[str, ...] = ("NYC", "LAX", "SEA", "MIA", "BOS")
AIRLINES: tuple[str, ...] = ("AA", "UA", "DL", "WN", "AS")
# Routes whose destination sits outside the US are flagged INTERNATIONAL for
# step 05-02 tax-rate selection. All current destinations are domestic, so
# we extend the catalog explicitly via ``_international_flights`` below to
# exercise the RouteKind.INTERNATIONAL branch without changing the shape of
# the happy-path search scenarios.
INTERNATIONAL_DESTINATIONS: frozenset[str] = frozenset({"LHR", "CDG", "NRT", "SYD"})
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


def _international_flights(base_fare: Money) -> list[Flight]:
    """Produce a handful of INTERNATIONAL flights (step 05-02).

    Deterministic: same routes, dates, airlines on every call. Included so
    the seeded catalog exercises both tax-rate branches without forcing
    every domestic scenario to assert on a RouteKind argument.
    """
    international_routes = (
        ("LAX", "LHR"),
        ("JFK", "CDG"),
        ("SFO", "NRT"),
        ("LAX", "SYD"),
    )
    flights: list[Flight] = []
    for route_index, (origin, destination) in enumerate(international_routes):
        for day_offset in range(CATALOG_DAYS):
            departure_date = CATALOG_START_DATE + timedelta(days=day_offset)
            departure_at = departure_date.replace(hour=21)  # evening long-haul
            arrival_at = departure_at + timedelta(hours=FLIGHT_DURATION_HOURS * 2)
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
                    route_kind=RouteKind.INTERNATIONAL,
                )
            )
    return flights


def _return_leg_flights(base_fare: Money) -> list[Flight]:
    """Mint return-leg flights so step-08 round-trip pairing has candidates.

    The baseline ``_routes()`` cross-product only emits origin∈ORIGINS and
    destination∈DESTINATIONS. NYC is a destination but not an origin, so
    there are zero NYC→LAX flights — a round-trip LAX→NYC→LAX can't pair
    without these. Similarly LHR, CDG, NRT, SYD are international
    destinations that never appear as origins. This helper adds the
    mirrored return legs for the pairs the milestone-08 scenarios
    exercise (LAX↔NYC, LAX↔LHR), keeping all earlier catalog invariants
    intact (same fare, same cabin, same 30-day window).
    """
    return_routes = (
        ("NYC", "LAX", RouteKind.DOMESTIC),
        ("LHR", "LAX", RouteKind.INTERNATIONAL),
    )
    flights: list[Flight] = []
    for route_index, (origin, destination, route_kind) in enumerate(return_routes):
        for day_offset in range(CATALOG_DAYS):
            departure_date = CATALOG_START_DATE + timedelta(days=day_offset)
            # Depart at 14:00 UTC — comfortably after any 08:00/13:00 outbound
            # arrival so the ≥2h buffer check has signal on same-day pairs.
            departure_at = departure_date.replace(hour=14)
            arrival_at = departure_at + timedelta(hours=FLIGHT_DURATION_HOURS)
            airline = AIRLINES[(route_index + day_offset) % len(AIRLINES)]
            date_iso = departure_date.date().isoformat()
            flight_id = f"FL-{origin}-{destination}-{date_iso}-{airline}-RT"
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
                    route_kind=route_kind,
                )
            )
    return flights


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
            # All ORIGINS × DESTINATIONS are US domestic; INTERNATIONAL
            # flights are appended separately below.
            route_kind = (
                RouteKind.INTERNATIONAL
                if destination in INTERNATIONAL_DESTINATIONS
                else RouteKind.DOMESTIC
            )
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
                    route_kind=route_kind,
                )
            )
    flights.extend(_international_flights(base_fare))
    flights.extend(_return_leg_flights(base_fare))
    return flights
