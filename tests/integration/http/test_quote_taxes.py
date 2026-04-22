"""Integration tests for taxes on ``POST /quotes``.

These tests exercise the FastAPI quote route end-to-end through ``TestClient``
against the real ``build_test_container``. They cover step 05-02's AC:

  * A quote for a DOMESTIC flight returns ``taxes`` in the response body
    equal to ``(base × multipliers + Σ surcharges) × domestic_rate``.
  * A quote for an INTERNATIONAL flight returns ``taxes`` equal to the
    post-multiplier base × international_rate.

Fees remain 0 this iteration (per the step brief) — that's exercised
implicitly (the response carries ``fees: "0.00"``) but the assertions
focus on taxes, which is the behavior introduced by this step.

Occupancy is driven by cabin state; a 100-seat cabin with all seats
AVAILABLE yields 0% occupancy, demand multiplier 1.00 — this keeps the
taxable-base arithmetic simple enough to reproduce on paper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight, RouteKind
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus


def _make_single_seat_cabin(quote_seat_id: str, total: int = 100) -> Cabin:
    """Cabin with ``total`` Economy STANDARD seats — all AVAILABLE so
    occupancy is 0% and the demand multiplier is 1.00. The quoted seat has
    kind STANDARD so no Appendix A surcharge applies: taxable_base = base
    × demand × time × day (no surcharge term).
    """
    cabin = Cabin()
    cabin.seats[SeatId(quote_seat_id)] = Seat(
        id=SeatId(quote_seat_id),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    for i in range(1, total):
        seat_id = SeatId(f"FILL-{i:03d}")
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=SeatStatus.AVAILABLE,
        )
    return cabin


def _seed_flight(
    container: Container,
    *,
    flight_id: str,
    route_kind: RouteKind,
    origin: str = "LAX",
    destination: str = "NYC",
    quote_seat_id: str = "12C",
    fare: str = "299",
) -> Flight:
    """Seed a Tuesday 2026-06-02 flight so time/day multipliers are stable.

    The test client's frozen clock is 2026-05-03 → 30 days out → time
    multiplier 0.85, demand 1.00 (empty cabin), Tuesday → day 0.85.
    Taxable base per Appendix B example 1 = 228.735 (before rounding).
    Rate applied at full precision; Money rounds to 2 dp at the boundary.
    """
    flight = Flight(
        id=FlightId(flight_id),
        origin=origin,
        destination=destination,
        departure_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),  # Tuesday
        arrival_at=datetime(2026, 6, 2, 13, 0, tzinfo=UTC),
        airline="MOCK",
        base_fare=Money.of(fare),
        cabin=_make_single_seat_cabin(quote_seat_id),
        route_kind=route_kind,
    )
    container.flight_repo.add(flight)
    return flight


@pytest.fixture
def domestic_client() -> TestClient:
    """Client bound to a container seeded with a DOMESTIC flight."""
    now = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
    container = build_test_container(now=now, audit_path=None, deterministic_ids=True)
    _seed_flight(
        container,
        flight_id="FL-DOM-NYC",
        route_kind=RouteKind.DOMESTIC,
        destination="NYC",
    )
    return TestClient(create_app(container=container))


@pytest.fixture
def international_client() -> TestClient:
    """Client bound to a container seeded with an INTERNATIONAL flight."""
    now = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
    container = build_test_container(now=now, audit_path=None, deterministic_ids=True)
    _seed_flight(
        container,
        flight_id="FL-INT-LHR",
        route_kind=RouteKind.INTERNATIONAL,
        destination="LHR",
    )
    return TestClient(create_app(container=container))


class TestQuoteTaxesByRouteKind:
    def test_quote_for_domestic_flight_returns_domestic_tax_in_breakdown(
        self, domestic_client: TestClient
    ) -> None:
        response = domestic_client.post(
            "/quotes",
            json={
                "flightId": "FL-DOM-NYC",
                "seatIds": ["12C"],
                "passengers": 1,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Appendix B example 1 context: 30 days out (time=0.90), Tuesday
        # (day=0.85), 0% occupancy (demand=1.00). Taxable base = 299 ×
        # 1.00 × 0.90 × 0.85 = 228.735. Domestic tax = 228.735 × 0.075 =
        # 17.155125 → Money.of rounds half-even to 17.16.
        expected_taxable_base = Decimal("299") * Decimal("1.00") * Decimal("0.90") * Decimal("0.85")
        expected_taxes = Money.of(expected_taxable_base * Decimal("0.075"))
        assert "taxes" in body, f"missing 'taxes' in response: {body!r}"
        assert Money.of(body["taxes"]) == expected_taxes, (
            f"expected taxes {expected_taxes.amount}, got {body['taxes']}"
        )
        # Fees this iteration default to 0 (FEES_TABLE empty).
        assert "fees" in body, f"missing 'fees' in response: {body!r}"
        assert Money.of(body["fees"]) == Money.of("0"), f"expected fees 0.00, got {body['fees']}"

    def test_quote_for_international_flight_returns_international_tax_in_breakdown(
        self, international_client: TestClient
    ) -> None:
        response = international_client.post(
            "/quotes",
            json={
                "flightId": "FL-INT-LHR",
                "seatIds": ["12C"],
                "passengers": 1,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Same flight context as domestic, different rate:
        # Taxable base = 228.735. International tax = 228.735 × 0.12 =
        # 27.4482 → Money.of rounds half-even to 27.45.
        expected_taxable_base = Decimal("299") * Decimal("1.00") * Decimal("0.90") * Decimal("0.85")
        expected_taxes = Money.of(expected_taxable_base * Decimal("0.12"))
        assert "taxes" in body, f"missing 'taxes' in response: {body!r}"
        assert Money.of(body["taxes"]) == expected_taxes, (
            f"expected taxes {expected_taxes.amount}, got {body['taxes']}"
        )
