"""InMemoryFlightRepository — unit tests.

Port-to-port at the driven-port scope: the test invokes the repository's public
Protocol surface (``add``, ``get``, ``search``) and asserts observable outcomes.
No internal state is inspected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from flights.adapters.inmemory.flight_repository import InMemoryFlightRepository
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId
from flights.domain.model.money import Money


def _make_flight(
    flight_id: str,
    origin: str,
    destination: str,
    departure_at: datetime,
    airline: str = "AA",
) -> Flight:
    return Flight(
        id=FlightId(flight_id),
        origin=origin,
        destination=destination,
        departure_at=departure_at,
        arrival_at=departure_at,  # duration not relevant for repo tests
        airline=airline,
        base_fare=Money(Decimal("299.00")),
        cabin=Cabin(seats={}),
    )


class TestInMemoryFlightRepositoryAddAndGet:
    def test_get_returns_flight_after_add(self) -> None:
        repo = InMemoryFlightRepository()
        flight = _make_flight(
            "FL-1", "LAX", "NYC", datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        )

        repo.add(flight)

        assert repo.get(FlightId("FL-1")) is flight

    def test_get_returns_none_for_unknown_flight(self) -> None:
        repo = InMemoryFlightRepository()
        assert repo.get(FlightId("MISSING")) is None

    def test_add_is_idempotent_for_same_id(self) -> None:
        repo = InMemoryFlightRepository()
        flight = _make_flight(
            "FL-1", "LAX", "NYC", datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        )

        repo.add(flight)
        repo.add(flight)

        assert repo.get(FlightId("FL-1")) is flight


class TestInMemoryFlightRepositorySearch:
    def test_search_returns_only_flights_matching_origin_destination_and_date(self) -> None:
        repo = InMemoryFlightRepository()
        match = _make_flight(
            "FL-MATCH", "LAX", "NYC", datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        )
        wrong_origin = _make_flight(
            "FL-WRONG-O", "SFO", "NYC", datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        )
        wrong_dest = _make_flight(
            "FL-WRONG-D", "LAX", "BOS", datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        )
        wrong_date = _make_flight(
            "FL-WRONG-DT", "LAX", "NYC", datetime(2026, 6, 2, 8, 0, tzinfo=UTC)
        )
        for f in (match, wrong_origin, wrong_dest, wrong_date):
            repo.add(f)

        results = repo.search("LAX", "NYC", "2026-06-01")

        assert results == [match]

    def test_search_returns_empty_list_when_no_matches(self) -> None:
        repo = InMemoryFlightRepository()
        repo.add(
            _make_flight(
                "FL-1", "LAX", "NYC", datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
            )
        )

        assert repo.search("SFO", "BOS", "2026-06-01") == []
