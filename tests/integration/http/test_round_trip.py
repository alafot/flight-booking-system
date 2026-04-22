"""Integration tests for /flights/search round-trip pairing (step 08-01).

Scope:

* Round-trip search returns paired outbound+return flights when
  ``returnDate`` is supplied.
* The pair-eligibility rule is "return.origin == outbound.destination AND
  return.departure_at >= outbound.arrival_at + 2h".
* Pagination operates on PAIRS (``pairCount`` reported alongside
  ``flightCount = 2 * pairCount``).
* Backwards compatibility: when ``returnDate`` is absent the endpoint
  returns the legacy one-way response shape (``flights`` / ``total``).

Tests enter through the FastAPI driving port and assert at the HTTP
response boundary — port-to-port at adapter scope. They run against the
real composition root with in-memory driven adapters.
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
    origin: str,
    destination: str,
    departure: datetime,
    duration_hours: int = 5,
    airline: str = "AA",
    fare: str = "299",
) -> None:
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


class TestRoundTripPairing:
    """Round-trip search composes two one-way searches into pairs."""

    def test_round_trip_pairs_outbound_with_return(
        self, client: TestClient, container: Container
    ) -> None:
        # One outbound LAX→NYC departing 08:00 (arrives 13:00) and one
        # return NYC→LAX departing 14:00 — buffer = 1h, FAILS the 2h rule.
        # We seed both a buffer-passing and a buffer-failing return to
        # exercise the filter end-to-end.
        outbound_dep = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        return_ok_dep = datetime(2026, 6, 8, 14, 0, tzinfo=UTC)
        _add_flight(
            container,
            flight_id="OUT-1",
            origin="LAX",
            destination="NYC",
            departure=outbound_dep,
        )
        _add_flight(
            container,
            flight_id="RET-OK",
            origin="NYC",
            destination="LAX",
            departure=return_ok_dep,
        )

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "returnDate": "2026-06-08",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert "pairs" in body
        assert body["pairCount"] == 1
        assert body["flightCount"] == 2
        pair = body["pairs"][0]
        assert pair["outbound"]["id"] == "OUT-1"
        assert pair["return"]["id"] == "RET-OK"
        # Outbound destination matches return origin.
        assert pair["return"]["origin"] == pair["outbound"]["destination"]
        # totalIndicativePrice is the sum of the two base fares.
        assert pair["totalIndicativePrice"] == "598.00"

    def test_round_trip_enforces_two_hour_buffer(
        self, client: TestClient, container: Container
    ) -> None:
        # Same-day round-trip exercises the 2h buffer rule. Outbound
        # arrives 13:00. A return departing 14:00 (1h gap) MUST NOT pair;
        # one departing 15:30 (2.5h gap) MUST pair.
        outbound_dep = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        return_too_close = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)
        return_ok = datetime(2026, 6, 1, 15, 30, tzinfo=UTC)
        _add_flight(
            container,
            flight_id="OUT-1",
            origin="LAX",
            destination="NYC",
            departure=outbound_dep,
        )
        _add_flight(
            container,
            flight_id="RET-TOO-CLOSE",
            origin="NYC",
            destination="LAX",
            departure=return_too_close,
        )
        _add_flight(
            container,
            flight_id="RET-OK",
            origin="NYC",
            destination="LAX",
            departure=return_ok,
        )

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "returnDate": "2026-06-01",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["pairCount"] == 1, f"only RET-OK should pair, got {body['pairs']!r}"
        assert body["pairs"][0]["return"]["id"] == "RET-OK"

    def test_round_trip_pagination_by_pairs(self, client: TestClient, container: Container) -> None:
        # 25 outbounds × 1 matching return-each (one-to-one by minute offset
        # on the return side, all sharing a buffer-safe departure window).
        outbound_base = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        return_base = datetime(2026, 6, 8, 16, 0, tzinfo=UTC)  # 3h after arrivals
        for i in range(25):
            _add_flight(
                container,
                flight_id=f"OUT-{i:03d}",
                origin="LAX",
                destination="NYC",
                departure=outbound_base + timedelta(minutes=i),
            )
            _add_flight(
                container,
                flight_id=f"RET-{i:03d}",
                origin="NYC",
                destination="LAX",
                departure=return_base + timedelta(minutes=i),
            )

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "returnDate": "2026-06-08",
                "page": 1,
            },
        )

        assert response.status_code == 200
        body = response.json()
        # Pair space = 25 outbounds × 25 returns (all returns are buffer-safe
        # against all outbounds since 16:00 - 13:24 > 2h). pairCount reports
        # the TOTAL pair space (not the page slice); the page returns at most
        # ``size`` pairs.
        assert body["pairCount"] == 25 * 25
        assert body["flightCount"] == 2 * 25 * 25
        assert len(body["pairs"]) == 20  # default size cap
        assert body["page"] == 1
        assert body["size"] == 20

    def test_one_way_unchanged_when_return_date_absent(
        self, client: TestClient, container: Container
    ) -> None:
        # Backwards compatibility: legacy response shape (``flights``/``total``)
        # is preserved when no returnDate is supplied.
        outbound_dep = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        _add_flight(
            container,
            flight_id="OUT-1",
            origin="LAX",
            destination="NYC",
            departure=outbound_dep,
        )

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert "flights" in body
        assert "pairs" not in body
        assert "pairCount" not in body
        assert "flightCount" not in body
        assert body["total"] == 1
        assert body["flights"][0]["id"] == "OUT-1"
