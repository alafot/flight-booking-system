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

from flights.domain.model.flight import RouteKind
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

# --- Appendix A: per-seat surcharges (ADR-004) -------------------------------
# Single source of truth for ``(seat_class, seat_kind) -> Money``. An entry
# here is the one place an Appendix A number is edited. Missing entries are
# treated by ``lookup_seat_surcharge`` as neutral (Money.of("0")) — the kind
# has no surcharge in that cabin.
#
# Premium Economy entries (below) are documented for the future ADR-007 flip
# day. ``SeatClass`` currently has no ``PREMIUM_ECONOMY`` member so these
# pairs are unreachable from any cabin fixture; they remain commented to
# preserve Appendix A coverage without widening the enum.
#
#     (SeatClass.PREMIUM_ECONOMY, SeatKind.STANDARD):    Money.of("0"),
#     (SeatClass.PREMIUM_ECONOMY, SeatKind.EXIT_ROW):   Money.of("50"),
#     (SeatClass.PREMIUM_ECONOMY, SeatKind.BULKHEAD):   Money.of("40"),
#     (SeatClass.PREMIUM_ECONOMY, SeatKind.WINDOW):     Money.of("30"),
SURCHARGES: dict[tuple[SeatClass, SeatKind], Money] = {
    # Economy
    (SeatClass.ECONOMY,  SeatKind.STANDARD):      Money.of("0"),
    (SeatClass.ECONOMY,  SeatKind.EXIT_ROW):      Money.of("35"),
    (SeatClass.ECONOMY,  SeatKind.FRONT_SECTION): Money.of("25"),
    (SeatClass.ECONOMY,  SeatKind.AISLE):         Money.of("15"),
    (SeatClass.ECONOMY,  SeatKind.WINDOW):        Money.of("15"),
    (SeatClass.ECONOMY,  SeatKind.MIDDLE):        Money.of("-5"),
    # Business
    (SeatClass.BUSINESS, SeatKind.STANDARD):       Money.of("0"),
    (SeatClass.BUSINESS, SeatKind.LIE_FLAT_SUITE): Money.of("200"),
    (SeatClass.BUSINESS, SeatKind.WINDOW_SUITE):   Money.of("100"),
    (SeatClass.BUSINESS, SeatKind.AISLE_ACCESS):   Money.of("75"),
    # First
    (SeatClass.FIRST,    SeatKind.STANDARD):      Money.of("0"),
    (SeatClass.FIRST,    SeatKind.PRIVATE_SUITE): Money.of("500"),
    (SeatClass.FIRST,    SeatKind.FRONT_ROW):     Money.of("150"),
}

# --- Step 05-02: taxes and fees ---------------------------------------------
# Two flat tax rates per ADR-007. Editing a rate is a one-location change —
# callers read through ``TAX_RATES[route_kind]`` (or via ``compute_taxes``).
# Per-jurisdiction rates are deferred; the dict shape generalises to that
# future state without a schema change.
TAX_RATES: dict[RouteKind, Decimal] = {
    RouteKind.DOMESTIC:      Decimal("0.075"),
    RouteKind.INTERNATIONAL: Decimal("0.12"),
}

# Flat per-quote fees table. Empty this iteration — the contract supports
# per-route or per-flight entries but no entries are populated until a
# future step wires a lookup. ``lookup_flat_fees`` returns ``Money.of("0")``
# for any miss, so today's quote service passes zero fees unconditionally.
FEES_TABLE: dict[str, Money] = {}


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
    """Return the Appendix A surcharge for ``(seat_class, kind)``.

    An unmapped pair returns ``Money.of("0")`` — the kind simply has no
    priced surcharge in that cabin class. Callers iterate seat ids; they do
    not need to branch on "known vs unknown" themselves.
    """
    return SURCHARGES.get((seat_class, kind), Money.of("0"))


def compute_taxes(taxable_base: Money, route_kind: RouteKind) -> Money:
    """Apply the flat tax rate for ``route_kind`` to ``taxable_base``.

    The caller is responsible for building the taxable base — per the step
    brief (ADR-007 reaffirmed): ``taxable_base = base × multipliers + Σ
    surcharges``. This function holds full Decimal precision; the final
    rounding happens when ``PriceBreakdown.total`` quantizes the sum
    (``base × mult + surcharges + taxes + fees``). See ADR-003 rounding
    policy + Appendix B worked examples.
    """
    rate = TAX_RATES[route_kind]
    return Money(taxable_base.amount * rate, taxable_base.currency)


def lookup_flat_fees(flight_id: str) -> Money:
    """Return the flat per-quote fee for ``flight_id`` (step 05-02).

    The table is empty this iteration — any flight_id yields ``Money.of("0")``.
    Kept as a function so future slices can plug a richer lookup without
    touching the QuoteService call site.
    """
    return FEES_TABLE.get(flight_id, Money.of("0"))
