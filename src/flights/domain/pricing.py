"""Dynamic pricing engine — pure function.

ADR-005: kept pure. No I/O, no clock, no randomness.
ADR-003: uses Decimal with ROUND_HALF_EVEN at the end.
Appendix B: three worked examples (228.74 / 897.00 / 1944.00 USD) are the
KPI-C1 anchors.

Boundary policy (ADR-005): left-inclusive, right-exclusive buckets for
``occupancy_pct``. The rule tables are the single authoritative source —
editing a multiplier means editing exactly one tuple here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum

from flights.domain.model.money import Money
from flights.domain.model.quote import PriceBreakdown, SeatSurchargeLine
from flights.domain.model.seat import SeatClass, SeatKind


class DayOfWeek(IntEnum):
    MON = 0
    TUE = 1
    WED = 2
    THU = 3
    FRI = 4
    SAT = 5
    SUN = 6


# --- Appendix B: demand multipliers ------------------------------------------
# Buckets are left-inclusive, right-exclusive: [lower, upper). Stored as
# (upper_bound_exclusive, multiplier) pairs, sorted ascending — lookup takes
# the first entry whose upper bound strictly exceeds the input percentage.
# The final bucket [96, ∞) uses Decimal("Infinity") so the lookup cannot fall
# off the end for any valid occupancy (0..100).
DEMAND_TABLE: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("31"), Decimal("1.00")),   # [0, 31)
    (Decimal("51"), Decimal("1.15")),   # [31, 51)
    (Decimal("71"), Decimal("1.35")),   # [51, 71)
    (Decimal("86"), Decimal("1.60")),   # [71, 86)
    (Decimal("96"), Decimal("2.00")),   # [86, 96)
    (Decimal("Infinity"), Decimal("2.50")),   # [96, ∞)
)

# --- Appendix B: time-to-departure multipliers -------------------------------
# Stored as (lower_bound_inclusive, multiplier) pairs, sorted DESCENDING by
# threshold — lookup takes the first entry whose lower bound is ≤ the input
# days-before-departure. 0 (same day) is the terminal entry.
TIME_TABLE: tuple[tuple[int, Decimal], ...] = (
    (60, Decimal("0.85")),  # ≥ 60 days
    (21, Decimal("0.90")),  # 21..59
    (7,  Decimal("1.00")),  # 7..20
    (3,  Decimal("1.20")),  # 3..6
    (1,  Decimal("1.50")),  # 1..2
    (0,  Decimal("2.00")),  # 0 (same day)
)

# --- Appendix B: day-of-week multipliers -------------------------------------
DOW_TABLE: dict[DayOfWeek, Decimal] = {
    DayOfWeek.MON: Decimal("0.90"),
    DayOfWeek.TUE: Decimal("0.85"),
    DayOfWeek.WED: Decimal("0.85"),
    DayOfWeek.THU: Decimal("0.95"),
    DayOfWeek.FRI: Decimal("1.25"),
    DayOfWeek.SAT: Decimal("1.15"),
    DayOfWeek.SUN: Decimal("1.30"),
}

# Appendix A — later step fills this from ADR-004.
SURCHARGES: dict[tuple[SeatClass, SeatKind], Money] = {}


@dataclass(frozen=True, slots=True)
class PricingInputs:
    base_fare: Money
    occupancy_pct: Decimal  # 0..100
    days_before_departure: int
    departure_dow: DayOfWeek
    surcharges: tuple[SeatSurchargeLine, ...] = ()
    taxes: Money = Money.of("0")
    fees: Money = Money.of("0")


def _demand_multiplier(occupancy_pct: Decimal) -> Decimal:
    """Left-inclusive, right-exclusive bucket lookup on DEMAND_TABLE."""
    for upper_exclusive, multiplier in DEMAND_TABLE:
        if occupancy_pct < upper_exclusive:
            return multiplier
    # Unreachable: the final bucket uses Decimal("Infinity").
    raise AssertionError(f"no demand bucket for occupancy_pct={occupancy_pct}")


def _time_multiplier(days_before_departure: int) -> Decimal:
    """Descending threshold lookup on TIME_TABLE."""
    for lower_inclusive, multiplier in TIME_TABLE:
        if days_before_departure >= lower_inclusive:
            return multiplier
    raise AssertionError(
        f"no time bucket for days_before_departure={days_before_departure}"
    )


def _day_multiplier(dow: DayOfWeek) -> Decimal:
    return DOW_TABLE[dow]


def price(inputs: PricingInputs) -> PriceBreakdown:
    """Compute price breakdown. Pure; deterministic; no I/O."""
    demand = _demand_multiplier(inputs.occupancy_pct)
    time = _time_multiplier(inputs.days_before_departure)
    dow = _day_multiplier(inputs.departure_dow)
    return PriceBreakdown(
        base_fare=inputs.base_fare,
        demand_multiplier=demand,
        time_multiplier=time,
        day_multiplier=dow,
        seat_surcharges=inputs.surcharges,
        taxes=inputs.taxes,
        fees=inputs.fees,
    )


def lookup_seat_surcharge(seat_class: SeatClass, kind: SeatKind) -> Money:
    raise AssertionError(
        "Not yet implemented — RED scaffold (pricing.lookup_seat_surcharge)"
    )
