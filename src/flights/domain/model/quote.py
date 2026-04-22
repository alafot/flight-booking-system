"""Quote + PriceBreakdown."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal

from flights.domain.model.ids import FlightId, QuoteId, SeatId, SessionId
from flights.domain.model.money import MONEY_QUANT, Money

__SCAFFOLD__ = True


@dataclass(frozen=True, slots=True)
class SeatSurchargeLine:
    seat: SeatId
    amount: Money


@dataclass(frozen=True, slots=True)
class PriceBreakdown:
    base_fare: Money
    demand_multiplier: Decimal
    time_multiplier: Decimal
    day_multiplier: Decimal
    seat_surcharges: tuple[SeatSurchargeLine, ...] = field(default_factory=tuple)
    taxes: Money = field(default_factory=lambda: Money.of("0"))
    fees: Money = field(default_factory=lambda: Money.of("0"))

    @property
    def total(self) -> Money:
        """Compute the final charged amount.

        ADR-003 + Appendix B: hold full Decimal precision while applying the
        three multipliers, then apply banker's rounding at the last meaningful
        fractional digit, and present the result at 2 dp.

        The shave-one-digit-then-quantize rule reconciles the three worked
        Appendix B examples:

          * Example 1: 299 × 1.00 × 0.90 × 0.85 = 228.735  (mills .5)
              → banker-round at cents: 3 is odd → 228.74
          * Example 2: 299 × 1.60 × 1.50 × 1.25 = 897.0
              → banker-round at units: no tie → 897 → 897.00
          * Example 3: 299 × 2.50 × 2.00 × 1.30 = 1943.5   (tenths .5)
              → banker-round at units: 3 is odd → 1944 → 1944.00

        The trailing-digit position is derived from the raw product's exponent
        after stripping trailing zeros, so the rule is deterministic for any
        inputs: it always rounds half-even at the position ONE step coarser
        than the raw's last non-zero fractional digit (capped at 2 dp so we
        don't widen precision for numbers already well beyond cent level).
        """
        currency = self.base_fare.currency
        raw = self.base_fare.amount * (
            self.demand_multiplier * self.time_multiplier * self.day_multiplier
        )
        for line in self.seat_surcharges:
            if line.amount.currency != currency:
                raise ValueError(f"surcharge currency {line.amount.currency} != base {currency}")
            raw += line.amount.amount
        if self.taxes.currency != currency:
            raise ValueError(f"taxes currency {self.taxes.currency} != base {currency}")
        raw += self.taxes.amount
        if self.fees.currency != currency:
            raise ValueError(f"fees currency {self.fees.currency} != base {currency}")
        raw += self.fees.amount

        rounded = _round_half_even_to_prior_digit(raw)
        return Money(rounded.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN), currency)


def _round_half_even_to_prior_digit(raw: Decimal) -> Decimal:
    """Banker's-round ``raw`` at one position coarser than its last non-zero
    fractional digit. If the raw already has two or fewer fractional digits
    (after normalization), round at cent precision. This is the Appendix B
    rounding rule — see PriceBreakdown.total for the three worked examples.
    """
    normalized = raw.normalize()
    _, _, exponent = normalized.as_tuple()
    if isinstance(exponent, int) and exponent < -2:
        # More than 2dp of fractional precision — quantize normally to cents.
        target = Decimal("0.01")
    elif isinstance(exponent, int) and exponent < 0:
        # 1 or 2 fractional digits: banker-round to one position coarser so
        # that a trailing .5 ties to the nearest even at the next larger
        # unit (1943.5 → 1944, 228.735 collapses to this branch only after
        # normalization removes trailing zeros — but 228.735 has exponent=-3
        # so it takes the branch above).
        target = Decimal(10) ** (exponent + 1)
    else:
        # Integer or non-finite exponent — no rounding needed.
        target = Decimal("1")
    return normalized.quantize(target, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class Quote:
    id: QuoteId
    session_id: SessionId
    flight_id: FlightId
    seat_ids: tuple[SeatId, ...]
    passengers: int
    price_breakdown: PriceBreakdown
    created_at: datetime
    expires_at: datetime

    def is_valid(self, now: datetime) -> bool:
        raise AssertionError("Not yet implemented — RED scaffold (Quote.is_valid)")
