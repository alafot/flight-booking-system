"""Pricing domain — unit tests.

Port-to-port at domain scope per nw-tdd-methodology: the public ``price``
function and the module-level rule tables ARE the driving port for the pricing
domain. No HTTP, no mocks, deterministic.

Coverage: the three Appendix B worked examples (to the cent), boundary-bucket
selection for demand/time/DOW, and structural invariants that preserve the
"single source of truth" property of the rule tables (ADR-005).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from flights.domain import pricing
from flights.domain.model.money import Money
from flights.domain.pricing import (
    DEMAND_TABLE,
    DOW_TABLE,
    TIME_TABLE,
    DayOfWeek,
    PricingInputs,
    price,
)


class TestAppendixBExamples:
    """Three worked examples from the brief (Appendix B). Each verifies the
    full pipeline: multiplier lookups × banker's rounding at the end.
    """

    @pytest.mark.parametrize(
        "occupancy,days_before,dow,expected_total",
        [
            # Example 1: empty Tuesday, 30 days out → 299 × 1.00 × 0.90 × 0.85
            (Decimal("0"), 30, DayOfWeek.TUE, "228.74"),
            # Example 2: 80% full Friday, 2 days out → 299 × 1.60 × 1.50 × 1.25
            (Decimal("80"), 2, DayOfWeek.FRI, "897.00"),
            # Example 3: 98% full Sunday, same-day → 299 × 2.50 × 2.00 × 1.30
            # Intermediate product is 1943.5 → half-even rounds to 1944.00
            # (4 is even, so 0.5 rounds down... wait, 0.5 rounds to nearest even:
            # between 1943 and 1944, the even one is 1944 → 1944.00)
            (Decimal("98"), 0, DayOfWeek.SUN, "1944.00"),
        ],
        ids=["example_1_empty_tuesday", "example_2_80pct_friday", "example_3_sameday_sunday"],
    )
    def test_to_the_cent(
        self,
        occupancy: Decimal,
        days_before: int,
        dow: DayOfWeek,
        expected_total: str,
    ) -> None:
        breakdown = price(
            PricingInputs(
                base_fare=Money.of("299"),
                occupancy_pct=occupancy,
                days_before_departure=days_before,
                departure_dow=dow,
            )
        )
        assert breakdown.total == Money.of(expected_total)


class TestDemandBucketBoundaries:
    """Left-inclusive, right-exclusive buckets per ADR-005.

    occupancy [0, 31) → 1.00 | [31, 51) → 1.15 | [51, 71) → 1.35
               [71, 86) → 1.60 | [86, 96) → 2.00 | [96, ∞) → 2.50
    """

    @pytest.mark.parametrize(
        "occupancy_pct,expected",
        [
            (Decimal("0"), Decimal("1.00")),
            (Decimal("30"), Decimal("1.00")),
            (Decimal("31"), Decimal("1.15")),
            (Decimal("50"), Decimal("1.15")),
            (Decimal("51"), Decimal("1.35")),
            (Decimal("70"), Decimal("1.35")),
            (Decimal("71"), Decimal("1.60")),
            (Decimal("85"), Decimal("1.60")),
            (Decimal("86"), Decimal("2.00")),
            (Decimal("95"), Decimal("2.00")),
            (Decimal("96"), Decimal("2.50")),
            (Decimal("100"), Decimal("2.50")),
        ],
    )
    def test_demand_multiplier_picks_correct_bucket(
        self, occupancy_pct: Decimal, expected: Decimal
    ) -> None:
        breakdown = price(
            PricingInputs(
                base_fare=Money.of("100"),
                occupancy_pct=occupancy_pct,
                days_before_departure=30,  # → time 0.90, stable
                departure_dow=DayOfWeek.MON,  # → dow 0.90, stable
            )
        )
        assert breakdown.demand_multiplier == expected


class TestTimeBucketBoundaries:
    """Days-before-departure buckets (right-inclusive at the upper end of the
    "tight" window; see task brief):

      days ≥ 60            → 0.85
      21 ≤ days ≤ 59       → 0.90
      7  ≤ days ≤ 20       → 1.00
      3  ≤ days ≤ 6        → 1.20
      1  ≤ days ≤ 2        → 1.50
      days == 0 (same day) → 2.00
    """

    @pytest.mark.parametrize(
        "days_before,expected",
        [
            (100, Decimal("0.85")),
            (60, Decimal("0.85")),
            (59, Decimal("0.90")),
            (21, Decimal("0.90")),
            (20, Decimal("1.00")),
            (7, Decimal("1.00")),
            (6, Decimal("1.20")),
            (3, Decimal("1.20")),
            (2, Decimal("1.50")),
            (1, Decimal("1.50")),
            (0, Decimal("2.00")),
        ],
    )
    def test_time_multiplier_picks_correct_bucket(
        self, days_before: int, expected: Decimal
    ) -> None:
        breakdown = price(
            PricingInputs(
                base_fare=Money.of("100"),
                occupancy_pct=Decimal("0"),  # demand 1.00, stable
                days_before_departure=days_before,
                departure_dow=DayOfWeek.MON,  # dow 0.90, stable
            )
        )
        assert breakdown.time_multiplier == expected


class TestDayOfWeekMultipliers:
    """Per Appendix B."""

    @pytest.mark.parametrize(
        "dow,expected",
        [
            (DayOfWeek.MON, Decimal("0.90")),
            (DayOfWeek.TUE, Decimal("0.85")),
            (DayOfWeek.WED, Decimal("0.85")),
            (DayOfWeek.THU, Decimal("0.95")),
            (DayOfWeek.FRI, Decimal("1.25")),
            (DayOfWeek.SAT, Decimal("1.15")),
            (DayOfWeek.SUN, Decimal("1.30")),
        ],
    )
    def test_day_multiplier_matches_appendix_b(self, dow: DayOfWeek, expected: Decimal) -> None:
        breakdown = price(
            PricingInputs(
                base_fare=Money.of("100"),
                occupancy_pct=Decimal("0"),  # demand 1.00
                days_before_departure=30,  # time 0.90
                departure_dow=dow,
            )
        )
        assert breakdown.day_multiplier == expected


class TestRuleTablesAsSingleSourceOfTruth:
    """ADR-005: the rule tables are the one authoritative location. Structural
    invariants — not value invariants — so edits to the Appendix B numbers
    flow through these tests without triggering spurious failures.
    """

    def test_rule_tables_are_module_level_constants(self) -> None:
        # Attribute access at module level, not via a factory or singleton.
        assert DEMAND_TABLE is pricing.DEMAND_TABLE
        assert TIME_TABLE is pricing.TIME_TABLE
        assert DOW_TABLE is pricing.DOW_TABLE
        # Tables are populated (the GREEN step fills them from Appendix B).
        assert len(DEMAND_TABLE) > 0, "DEMAND_TABLE must be populated"
        assert len(TIME_TABLE) > 0, "TIME_TABLE must be populated"
        # DOW_TABLE has an entry for every day of the week.
        assert set(DOW_TABLE.keys()) == set(DayOfWeek), (
            f"DOW_TABLE must cover all 7 days, got {set(DOW_TABLE.keys())}"
        )
