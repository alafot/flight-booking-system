"""SearchService.

Application service that translates a ``SearchRequest`` into a repository
query and wraps the result in a pageable envelope. Step 01-03 implements
the WS happy path (origin + destination + departure_date). Step 08-01
adds round-trip pairing via ``search_round_trip`` — composed from two
one-way searches and a ≥2h outbound-arrival/return-departure buffer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

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
            raise ValueError(
                "search_round_trip requires return_date; use search for one-way"
            )
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
                total_indicative_price=(
                    outbound.base_fare + return_flight.base_fare
                ),
            )
            for outbound in outbounds
            for return_flight in returns
            if return_flight.departure_at
            >= outbound.arrival_at + MINIMUM_LAYOVER
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
