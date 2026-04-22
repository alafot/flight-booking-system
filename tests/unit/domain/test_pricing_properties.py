"""Pricing domain — property tests (Hypothesis).

ADR-005 commits to property-based testability over 1000+ inputs: the pricing
function is pure, so we can assert determinism and positivity across the
entire valid input space without a clock or any I/O.

Three properties:
  1. Determinism — same inputs always yield the same output.
  2. Positivity — total is always > 0 when base fare is > 0.
  3. No hidden clock/randomness dependency — enforced by static inspection of
     the pricing module's imports.
"""

from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from flights.domain import pricing
from flights.domain.model.money import Money
from flights.domain.pricing import DayOfWeek, PricingInputs, price


# Strategy: realistic pricing inputs. Bounds match the domain's documented
# valid ranges (occupancy 0..100, non-negative days before departure).
_pricing_inputs = st.builds(
    PricingInputs,
    base_fare=st.decimals(
        min_value=Decimal("1"),
        max_value=Decimal("10000"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ).map(lambda d: Money.of(d)),
    occupancy_pct=st.integers(min_value=0, max_value=100).map(Decimal),
    days_before_departure=st.integers(min_value=0, max_value=365),
    departure_dow=st.sampled_from(list(DayOfWeek)),
)


@given(inputs=_pricing_inputs)
@settings(max_examples=1000, deadline=None)
def test_price_is_deterministic_for_random_inputs(inputs: PricingInputs) -> None:
    """Same inputs → same output. A second call must return an equal
    PriceBreakdown. Violations would indicate hidden state or a clock read."""
    first = price(inputs)
    second = price(inputs)
    assert first == second


@given(inputs=_pricing_inputs)
@settings(max_examples=1000, deadline=None)
def test_price_is_positive_for_random_valid_inputs(inputs: PricingInputs) -> None:
    """Every multiplier in Appendix B is strictly positive and the base fare
    is strictly positive by construction (strategy min=1), so the total must
    be strictly positive. This catches silent sign flips and any rounding
    pathology that could produce a zero total."""
    breakdown = price(inputs)
    assert breakdown.total.amount > Decimal("0"), (
        f"total must be > 0, got {breakdown.total} for {inputs}"
    )


def test_pricing_module_has_no_clock_or_random_imports() -> None:
    """ADR-005 forbids ``datetime``, ``random``, ``time`` and ``logging`` in
    the pricing module. We enforce that statically by parsing the source —
    runtime checks could be evaded by local imports inside a function."""
    module_path = pathlib.Path(pricing.__file__)
    tree = ast.parse(module_path.read_text())
    forbidden = {"datetime", "random", "time", "logging"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in forbidden:
                    found.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in forbidden:
                    found.add(top)
    assert not found, f"pricing.py must not import {forbidden}; found {found} (ADR-005)"
