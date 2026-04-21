"""SearchService.

Application service that translates a ``SearchRequest`` into a repository
query and wraps the result in a pageable envelope. Step 01-03 implements
the WS happy path (origin + destination + departure_date). Pagination
limits/airline filters and return-date round-trips come in Phase 02.
"""

from __future__ import annotations

from dataclasses import dataclass

from flights.domain.model.flight import Flight
from flights.domain.ports import Clock, FlightRepository


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
