"""Integration tests for /flights/search filter query params (step 08-02).

Scope:

* ``airline`` restricts one-way and round-trip results to flights whose
  ``airline`` matches exactly (IATA code). For round-trip, BOTH legs of
  a pair must match.
* ``minPrice``/``maxPrice`` restrict by ``baseFare`` (one-way) or
  ``totalIndicativePrice`` (round-trip), inclusive on both ends.
* ``departureTimeFrom``/``departureTimeTo`` restrict OUTBOUND departure
  time to the local-time window [HH:MM, HH:MM], inclusive.
* Filters compose (AND) — applying ``airline`` + ``maxPrice`` yields the
  intersection.
* Filters are commutative — query-string order does not change the
  response body.

Tests enter through the FastAPI driving port and assert at the HTTP
response boundary, matching the established round-trip integration
style (see ``test_round_trip.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId
from flights.domain.model.money import Money


@pytest.fixture
def container() -> Container:
    now = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
    return build_test_container(now=now, audit_path=None, deterministic_ids=True)


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container=container))


def _add_flight(
    container: Container,
    *,
    flight_id: str,
    origin: str = "LAX",
    destination: str = "NYC",
    departure: datetime | None = None,
    duration_hours: int = 5,
    airline: str = "AA",
    fare: str = "299",
) -> None:
    if departure is None:
        departure = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    container.flight_repo.add(
        Flight(
            id=FlightId(flight_id),
            origin=origin,
            destination=destination,
            departure_at=departure,
            arrival_at=departure + timedelta(hours=duration_hours),
            airline=airline,
            base_fare=Money.of(fare),
            cabin=Cabin(),
        )
    )


class TestAirlineFilter:
    """Exact-match airline (IATA code) filter."""

    def test_airline_filter_restricts_to_exact_iata_match(
        self, client: TestClient, container: Container
    ) -> None:
        # Seed two airlines on the same route+date; the filter must
        # return only the airline asked for.
        _add_flight(container, flight_id="FL-AA-1", airline="AA")
        _add_flight(container, flight_id="FL-UA-1", airline="UA")

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "airline": "AA",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert len(body["flights"]) == 1
        assert body["flights"][0]["id"] == "FL-AA-1"
        assert body["flights"][0]["airline"] == "AA"


class TestPriceRangeFilter:
    """Inclusive price-range filter on baseFare (one-way) /
    totalIndicativePrice (round-trip)."""

    def test_price_range_filter_uses_base_fare_for_one_way(
        self, client: TestClient, container: Container
    ) -> None:
        # Three fares: below (150), inside (300), above (600).
        _add_flight(container, flight_id="FL-CHEAP", fare="150")
        _add_flight(container, flight_id="FL-MID", fare="300")
        _add_flight(container, flight_id="FL-PREMIUM", fare="600")

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "minPrice": 200,
                "maxPrice": 500,
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        ids = sorted(f["id"] for f in body["flights"])
        assert ids == ["FL-MID"]
        assert body["total"] == 1

    def test_price_range_filter_uses_total_indicative_for_round_trip(
        self, client: TestClient, container: Container
    ) -> None:
        # Round-trip: outbound + return summed must land in the window.
        # Outbound 150 + Return 150 = 300 → inside [200, 500].
        # Outbound 300 + Return 300 = 600 → outside [200, 500].
        outbound_dep = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        return_dep = datetime(2026, 6, 8, 14, 0, tzinfo=UTC)
        _add_flight(
            container, flight_id="OUT-CHEAP", fare="150",
            origin="LAX", destination="NYC", departure=outbound_dep,
        )
        _add_flight(
            container, flight_id="OUT-MID", fare="300",
            origin="LAX", destination="NYC", departure=outbound_dep,
        )
        _add_flight(
            container, flight_id="RET-CHEAP", fare="150",
            origin="NYC", destination="LAX", departure=return_dep,
        )
        _add_flight(
            container, flight_id="RET-MID", fare="300",
            origin="NYC", destination="LAX", departure=return_dep,
        )

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "returnDate": "2026-06-08",
                "minPrice": 200,
                "maxPrice": 500,
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        # Expected pairs:
        #   CHEAP+CHEAP = 300 (in range)
        #   CHEAP+MID   = 450 (in range)
        #   MID+CHEAP   = 450 (in range)
        #   MID+MID     = 600 (out of range)
        assert body["pairCount"] == 3
        for pair in body["pairs"]:
            total = float(pair["totalIndicativePrice"])
            assert 200 <= total <= 500, f"pair total {total} outside range"


class TestDepartureTimeWindowFilter:
    """Inclusive HH:MM departure-time window filter."""

    def test_departure_time_window_filter(
        self, client: TestClient, container: Container
    ) -> None:
        # Three departures: 07:00 (before), 12:00 (inside), 19:00 (after).
        _add_flight(
            container, flight_id="FL-EARLY",
            departure=datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
        )
        _add_flight(
            container, flight_id="FL-MID",
            departure=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        )
        _add_flight(
            container, flight_id="FL-LATE",
            departure=datetime(2026, 6, 1, 19, 0, tzinfo=UTC),
        )

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "departureTimeFrom": "09:00",
                "departureTimeTo": "17:00",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        ids = sorted(f["id"] for f in body["flights"])
        assert ids == ["FL-MID"]


class TestFilterComposition:
    """AND composition and commutativity of filters."""

    def test_filters_compose_and_are_commutative(
        self, client: TestClient, container: Container
    ) -> None:
        # Seed a 4-flight grid:
        #   AA@299  — matches airline AND maxPrice 500
        #   AA@800  — matches airline only
        #   UA@299  — matches maxPrice only
        #   UA@800  — matches neither
        _add_flight(container, flight_id="AA-CHEAP", airline="AA", fare="299")
        _add_flight(container, flight_id="AA-PREMIUM", airline="AA", fare="800")
        _add_flight(container, flight_id="UA-CHEAP", airline="UA", fare="299")
        _add_flight(container, flight_id="UA-PREMIUM", airline="UA", fare="800")

        # Query 1: airline first, then maxPrice.
        r1 = client.get(
            "/flights/search",
            params=[
                ("origin", "LAX"),
                ("destination", "NYC"),
                ("departureDate", "2026-06-01"),
                ("airline", "AA"),
                ("maxPrice", "500"),
            ],
        )
        # Query 2: maxPrice first, then airline.
        r2 = client.get(
            "/flights/search",
            params=[
                ("origin", "LAX"),
                ("destination", "NYC"),
                ("departureDate", "2026-06-01"),
                ("maxPrice", "500"),
                ("airline", "AA"),
            ],
        )

        assert r1.status_code == 200 == r2.status_code
        body1 = r1.json()
        body2 = r2.json()
        # AND: intersection is the single AA@299 flight.
        ids1 = sorted(f["id"] for f in body1["flights"])
        assert ids1 == ["AA-CHEAP"]
        # Commutativity: identical result sets regardless of param order.
        ids2 = sorted(f["id"] for f in body2["flights"])
        assert ids1 == ids2
        assert body1["total"] == body2["total"] == 1
