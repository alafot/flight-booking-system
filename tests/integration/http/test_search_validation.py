"""Integration tests for /flights/search pagination and per-field validation.

Scope for step 02-02:

* Pagination defaults: 30 matching flights → page 1 returns 20, page 2 returns 10.
* Size clamping: ``size=50`` is clamped to 20 (we chose "clamp" per the feature).
* Per-field validation: each invalid input returns HTTP 400 with an ``errors``
  list containing an entry whose ``field`` names the offending parameter.

These tests enter through the driving port (FastAPI HTTP boundary) and assert
at the HTTP response boundary — port-to-port at adapter scope. They run against
the real composition root (in-memory driven adapters).
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


def _seed_n_flights_on_route(
    container: Container,
    *,
    n: int,
    origin: str,
    destination: str,
    date: str,
) -> None:
    """Seed ``n`` distinct flights that all match (origin, destination, date).

    Different airlines and departure times keep ids unique while preserving
    the filter match — so a single search returns all ``n`` flights.
    """
    base_departure = datetime.fromisoformat(f"{date}T00:00:00+00:00")
    for i in range(n):
        departure = base_departure + timedelta(minutes=i)
        container.flight_repo.add(
            Flight(
                id=FlightId(f"FL-{origin}-{destination}-{date}-{i:03d}"),
                origin=origin,
                destination=destination,
                departure_at=departure,
                arrival_at=departure + timedelta(hours=5),
                airline="AA",
                base_fare=Money.of("299"),
                cabin=Cabin(),
            )
        )


class TestSearchPagination:
    """The service paginates large result sets and caps page size at 20."""

    def test_page_1_returns_first_20_flights_and_page_2_returns_remaining(
        self, client: TestClient, container: Container
    ) -> None:
        _seed_n_flights_on_route(
            container, n=30, origin="LAX", destination="NYC", date="2026-06-01"
        )

        page1 = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "page": 1,
            },
        )
        page2 = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "page": 2,
            },
        )

        assert page1.status_code == 200
        assert page2.status_code == 200
        body1, body2 = page1.json(), page2.json()
        assert len(body1["flights"]) == 20
        assert len(body2["flights"]) == 10
        assert body1["total"] == 30
        assert body2["total"] == 30
        assert body1["page"] == 1
        assert body2["page"] == 2
        # No flight id repeats across the two pages.
        ids1 = {f["id"] for f in body1["flights"]}
        ids2 = {f["id"] for f in body2["flights"]}
        assert not (ids1 & ids2), "page 1 and page 2 must not overlap"

    def test_size_above_maximum_is_clamped_to_20(
        self, client: TestClient, container: Container
    ) -> None:
        _seed_n_flights_on_route(
            container, n=30, origin="LAX", destination="NYC", date="2026-06-01"
        )

        response = client.get(
            "/flights/search",
            params={
                "origin": "LAX",
                "destination": "NYC",
                "departureDate": "2026-06-01",
                "size": 50,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["flights"]) == 20
        assert body["size"] == 20


class TestSearchInputValidation:
    """Each invalid query parameter returns 400 with a per-field error entry."""

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("origin", "XX"),
            ("origin", "LosAngeles"),
            ("destination", "123"),
            ("departureDate", "not-a-date"),
            ("passengers", 0),
            ("passengers", 10),
            ("class", "COACH"),
        ],
    )
    def test_invalid_input_returns_400_with_error_for_field(
        self, client: TestClient, field: str, bad_value: object
    ) -> None:
        params: dict[str, object] = {
            "origin": "LAX",
            "destination": "NYC",
            "departureDate": "2026-06-01",
            "passengers": 1,
        }
        params[field] = bad_value

        response = client.get("/flights/search", params=params)

        assert response.status_code == 400, (
            f"expected 400 for {field}={bad_value!r}, got {response.status_code}: "
            f"{response.text}"
        )
        body = response.json()
        assert isinstance(body.get("errors"), list), (
            f"expected 'errors' list in body, got {body!r}"
        )
        reported_fields = [e.get("field") for e in body["errors"]]
        assert field in reported_fields, (
            f"expected error for field {field!r}, got {reported_fields!r}"
        )
