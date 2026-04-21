"""Unit tests for the seeded catalog fixture.

The catalog fixture is a pure data-generation function whose public signature
(``seeded_catalog() -> list[Flight]``) is itself the driving port. Port-to-port
at domain scope: we call the function and assert on its return value.
"""

from __future__ import annotations

from tests.fixtures.catalog import seeded_catalog


def test_seeded_catalog_yields_at_least_200_flights() -> None:
    flights = seeded_catalog()
    assert len(flights) >= 200


def test_seeded_catalog_covers_20_plus_routes() -> None:
    flights = seeded_catalog()
    routes = {(f.origin, f.destination) for f in flights}
    assert len(routes) >= 20


def test_seeded_catalog_covers_5_plus_airlines() -> None:
    flights = seeded_catalog()
    airlines = {f.airline for f in flights}
    assert len(airlines) >= 5


def test_seeded_catalog_covers_30_plus_departure_dates() -> None:
    flights = seeded_catalog()
    dates = {f.departure_at.date() for f in flights}
    assert len(dates) >= 30


def test_seeded_catalog_is_deterministic() -> None:
    first = seeded_catalog()
    second = seeded_catalog()
    assert len(first) == len(second)
    assert [f.id.value for f in first] == [f.id.value for f in second]
    assert [f.departure_at for f in first] == [f.departure_at for f in second]
