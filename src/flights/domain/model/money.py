"""Money value object.

Per ADR-003: every Money value is a ``decimal.Decimal`` quantized to two
decimal places using banker's rounding (``ROUND_HALF_EVEN``). The domain
layer treats ``float`` as forbidden; all arithmetic goes through this type.

Money is an immutable value object (frozen dataclass) — equality is by
value, instances are hashable, and every operation returns a new instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

MONEY_QUANT = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Money.amount must be Decimal")

    @classmethod
    def of(cls, value: str | int | Decimal, currency: str = "USD") -> Money:
        return cls(_quantize(Decimal(value)), currency)

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ValueError(
                f"cannot add Money of different currencies: {self.currency} + {other.currency}"
            )
        return Money(_quantize(self.amount + other.amount), self.currency)

    def __mul__(self, factor: Decimal) -> Money:
        return Money(_quantize(self.amount * factor), self.currency)
