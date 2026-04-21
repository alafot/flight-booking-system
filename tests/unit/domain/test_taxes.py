"""Tax rates and computation — unit tests.

Port-to-port at domain scope per nw-tdd-methodology: the public
``compute_taxes`` function and the module-level ``TAX_RATES`` table ARE the
driving port for this slice. No HTTP, no mocks, deterministic.

Coverage (step 05-02 AC):
  * ``TAX_RATES[RouteKind.DOMESTIC]`` is the configured domestic rate (7.5%).
  * ``TAX_RATES[RouteKind.INTERNATIONAL]`` is the configured international
    rate (12%).
  * ``compute_taxes`` applied to a domestic flight's taxable base returns
    ``taxable_base × domestic_rate`` in the same currency.
  * ``compute_taxes`` applied to an international flight's taxable base
    returns ``taxable_base × international_rate`` in the same currency.
  * The taxable base argument represents ``base × multipliers + Σ
    surcharges``; the function applies the rate to whatever Money value it
    receives (the caller is responsible for building the taxable base).

Test-budget: 5 distinct behaviors × 2 = 10 tests. Actual: 5 tests (one per
behavior, no parametrized explosion needed — the constants and the two
rate-applications are straightforward).
"""

from __future__ import annotations

from decimal import Decimal

from flights.domain.model.money import Money
from flights.domain.pricing import TAX_RATES, compute_taxes
from flights.domain.model.flight import RouteKind


class TestTaxRatesConstants:
    """The rate table is the single source of truth (ADR-005 style) — editing
    a rate is a one-location change. These tests pin the two enabled entries
    so a future edit shows up here deliberately.
    """

    def test_domestic_rate_is_7_5_percent(self) -> None:
        assert TAX_RATES[RouteKind.DOMESTIC] == Decimal("0.075")

    def test_international_rate_is_12_percent(self) -> None:
        assert TAX_RATES[RouteKind.INTERNATIONAL] == Decimal("0.12")


class TestComputeTaxesByRouteKind:
    """Behavior: ``compute_taxes(taxable_base, route_kind)`` multiplies the
    taxable base amount by ``TAX_RATES[route_kind]`` and returns a Money
    in the same currency at full Decimal precision (rounding deferred to
    ``PriceBreakdown.total`` per ADR-003).
    """

    def test_compute_taxes_for_domestic_route_applies_domestic_rate(self) -> None:
        # Taxable base of $200 × 7.5% = exactly $15. Decimal arithmetic
        # is exact here so the value equality holds without quantization
        # concerns.
        taxes = compute_taxes(Money.of("200"), RouteKind.DOMESTIC)
        assert taxes.amount == Decimal("200.00") * Decimal("0.075")
        assert taxes.currency == "USD"

    def test_compute_taxes_for_international_route_applies_international_rate(
        self,
    ) -> None:
        # Taxable base of $200 × 12% = exactly $24.
        taxes = compute_taxes(Money.of("200"), RouteKind.INTERNATIONAL)
        assert taxes.amount == Decimal("200.00") * Decimal("0.12")
        assert taxes.currency == "USD"


class TestComputeTaxesOnPostMultiplierBase:
    """Behavior: the taxable base is ``(base × multipliers + Σ surcharges)``
    — the taxes line scales with the multipliers, not with the raw base
    fare. This test pins that the rate is applied to whatever value is
    passed (domain contract), so callers can confidently pre-compute the
    post-multiplier base.
    """

    def test_compute_taxes_uses_taxable_base_inclusive_of_multipliers(
        self,
    ) -> None:
        # A post-multiplier base of 299 × 2.50 × 2.00 × 1.30 = 1943.50
        # (Appendix B example 3 raw product). Domestic 7.5% applied at full
        # precision yields 145.7625 exactly — compute_taxes returns the
        # unquantized Decimal so PriceBreakdown.total can round once at the end.
        post_multiplier_base = Money.of("1943.50")
        taxes = compute_taxes(post_multiplier_base, RouteKind.DOMESTIC)
        assert taxes.amount == Decimal("145.7625")
        assert taxes.currency == "USD"
