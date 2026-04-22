"""SearchService.

Application service that translates a ``SearchRequest`` into a repository
query and wraps the result in a pageable envelope. Step 01-03 implements
the WS happy path (origin + destination + departure_date). Step 08-01
adds round-trip pairing via ``search_round_trip`` — composed from two
one-way searches and a ≥2h outbound-arrival/return-departure buffer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from decimal import Decimal

from flights.domain.model.flight import Flight
from flights.domain.model.money import Money
from flights.domain.ports import Clock, FlightRepository

# ADR-007: round-trip pairs require a ≥2h layover between outbound
# arrival and return departure. The constant is kept here (not in the
# HTTP adapter) because the rule is a domain concern; the adapter only
# translates query params and renders the response body.
MINIMUM_LAYOVER = timedelta(hours=2)


@dataclass
class SearchRequest:
    origin: str
    destination: str
    departure_date: str
    passengers: int = 1
    page: int = 1
    size: int = 20
    airline: str | None = None
    return_date: str | None = None
    # Step 08-02: post-search filters. All optional; ``None`` means the
    # filter is not applied. ``min_price``/``max_price`` are inclusive
    # bounds, the time window is an inclusive [from, to] HH:MM range.
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    departure_time_from: time | None = None
    departure_time_to: time | None = None


@dataclass
class SearchResult:
    flights: list[Flight]
    page: int
    size: int
    total: int


@dataclass
class FlightPair:
    """A single round-trip pair with the indicative total base fare.

    ``total_indicative_price`` sums the two flights' base_fares (ADR-007:
    multipliers and taxes are quote-time concerns; the search surface
    shows only the indicative figure clients use to rank options).
    """

    outbound: Flight
    return_flight: Flight
    total_indicative_price: Money


@dataclass
class RoundTripResult:
    """Pageable round-trip envelope.

    ``pair_count`` is the TOTAL number of eligible pairs (filtered by the
    layover rule and origin-match invariant), not the size of the current
    page. ``flight_count = 2 * pair_count`` is redundant on paper but
    pinned in the contract so HTTP clients don't multiply themselves.
    """

    pairs: list[FlightPair]
    page: int
    size: int
    pair_count: int

    @property
    def flight_count(self) -> int:
        return 2 * self.pair_count


class SearchService:
    def __init__(self, flights: FlightRepository, clock: Clock) -> None:
        self._flights = flights
        self._clock = clock

    def search(self, request: SearchRequest) -> SearchResult:
        matches = self._flights.search(
            origin=request.origin,
            destination=request.destination,
            departure_date=request.departure_date,
            airline=request.airline,
        )
        # Step 08-02: post-search filters (price range, time window).
        # Airline is already handled by the repository. Price and time
        # are applied in-application so the repository port signature
        # stays narrow — adding them to the port would force every
        # adapter (including future SQL/Elasticsearch ones) to duplicate
        # the same predicate logic.
        matches = _apply_price_filter(
            matches,
            min_price=request.min_price,
            max_price=request.max_price,
            price_of=lambda flight: flight.base_fare.amount,
        )
        matches = _apply_time_window_filter(
            matches,
            time_from=request.departure_time_from,
            time_to=request.departure_time_to,
        )
        return SearchResult(
            flights=matches,
            page=request.page,
            size=request.size,
            total=len(matches),
        )

    def search_round_trip(self, request: SearchRequest) -> RoundTripResult:
        """Compose two one-way searches into a paired round-trip response.

        Algorithm (ADR-007):

        1. Query outbounds on (origin → destination, departure_date).
        2. Query returns on (destination → origin, return_date).
        3. Cross-product, retaining only pairs where
           ``return.departure_at >= outbound.arrival_at + 2h``.
        4. Sort pairs by (outbound.departure_at, return.departure_at) for
           deterministic pagination.
        5. Apply page/size slicing to the pair list.

        ``request.return_date`` MUST be set by the caller; the HTTP layer
        guards this. The method raises ``ValueError`` on a missing return
        date rather than silently degrading to a one-way search — that
        branch belongs to ``search``.
        """
        if request.return_date is None:
            raise ValueError("search_round_trip requires return_date; use search for one-way")
        outbounds = self._flights.search(
            origin=request.origin,
            destination=request.destination,
            departure_date=request.departure_date,
            airline=request.airline,
        )
        returns = self._flights.search(
            origin=request.destination,
            destination=request.origin,
            departure_date=request.return_date,
            airline=request.airline,
        )
        eligible = [
            FlightPair(
                outbound=outbound,
                return_flight=return_flight,
                total_indicative_price=(outbound.base_fare + return_flight.base_fare),
            )
            for outbound in outbounds
            for return_flight in returns
            if return_flight.departure_at >= outbound.arrival_at + MINIMUM_LAYOVER
        ]
        # Step 08-02: post-pair filters. Price filter applies to the
        # pair's ``total_indicative_price`` (the indicative total the
        # ranking client sees). The time window applies to the OUTBOUND
        # leg only — ADR-007 keeps the return-leg window out of scope
        # until a later slice adds a dedicated ``returnTimeFrom/To``
        # pair of params.
        eligible = _apply_price_filter(
            eligible,
            min_price=request.min_price,
            max_price=request.max_price,
            price_of=lambda pair: pair.total_indicative_price.amount,
        )
        if request.departure_time_from is not None or request.departure_time_to is not None:
            eligible = [
                pair
                for pair in eligible
                if _is_within_time_window(
                    pair.outbound.departure_at.time(),
                    request.departure_time_from,
                    request.departure_time_to,
                )
            ]
        eligible.sort(
            key=lambda pair: (
                pair.outbound.departure_at,
                pair.return_flight.departure_at,
            )
        )
        return RoundTripResult(
            pairs=eligible,
            page=request.page,
            size=request.size,
            pair_count=len(eligible),
        )


def _apply_price_filter[T](
    items: list[T],
    *,
    min_price: Decimal | None,
    max_price: Decimal | None,
    price_of,
) -> list[T]:
    """Return items whose ``price_of(item)`` lies in [min_price, max_price].

    Both bounds are optional and inclusive. ``None`` means the bound is
    open on that side (i.e. no lower/upper limit). A no-filter call
    (both bounds ``None``) returns the list unchanged.
    """
    if min_price is None and max_price is None:
        return items

    def in_range(item: T) -> bool:
        price = price_of(item)
        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False
        return True

    return [item for item in items if in_range(item)]


def _apply_time_window_filter(
    flights: list[Flight],
    *,
    time_from: time | None,
    time_to: time | None,
) -> list[Flight]:
    """Filter flights whose departure time falls in the [from, to] window.

    The window is inclusive on both ends; ``None`` means the side is
    unbounded. Compared against ``flight.departure_at.time()`` so the
    result is timezone-naive — matches the AC wording "local time".
    """
    if time_from is None and time_to is None:
        return flights
    return [
        flight
        for flight in flights
        if _is_within_time_window(
            flight.departure_at.time(),
            time_from,
            time_to,
        )
    ]


def _is_within_time_window(
    candidate: time,
    time_from: time | None,
    time_to: time | None,
) -> bool:
    if time_from is not None and candidate < time_from:
        return False
    if time_to is not None and candidate > time_to:
        return False
    return True
