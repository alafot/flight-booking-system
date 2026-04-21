"""Money value object — unit tests.

These are port-to-port tests at the domain-model boundary: `Money` is a pure
value object whose public signature (`.of`, `__add__`, `__mul__`, equality)
IS the driving port. No I/O, no mocks, deterministic.

Rounding policy: ROUND_HALF_EVEN (banker's rounding), quantized to 2 decimal
places on every Money instance. Verified against ADR-003 and Appendix B
worked examples of the brief (covered in step 04-01, not here).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from flights.domain.model.money import Money


class TestMoneyConstruction:
    @pytest.mark.parametrize("raw", ["299", 299, Decimal("299")])
    def test_of_quantizes_input_to_two_decimal_places(self, raw: object) -> None:
        assert Money.of(raw) == Money(Decimal("299.00"))  # type: ignore[arg-type]

    def test_of_defaults_currency_to_usd(self) -> None:
        assert Money.of("1").currency == "USD"

    def test_of_accepts_explicit_currency(self) -> None:
        assert Money.of("1", "EUR").currency == "EUR"


class TestMoneyBankersRounding:
    """ADR-003: ROUND_HALF_EVEN on quantize to 2dp."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # .5 rounds toward nearest EVEN digit
            ("299.735", "299.74"),   # 3 is odd → round up to 4 (even)
            ("299.745", "299.74"),   # 4 is even → stays at 4
            ("299.755", "299.76"),   # 5 is odd → round up to 6 (even)
            ("299.765", "299.76"),   # 6 is even → stays at 6
            # plain truncation cases
            ("299.731", "299.73"),
            ("299.739", "299.74"),
        ],
    )
    def test_quantizes_with_bankers_rounding(self, raw: str, expected: str) -> None:
        assert Money.of(raw).amount == Decimal(expected)


class TestMoneyArithmetic:
    def test_addition_returns_new_money_with_summed_amount(self) -> None:
        assert Money.of("1") + Money.of("2") == Money.of("3")

    def test_addition_result_is_quantized_to_two_decimal_places(self) -> None:
        # Construct Monies with un-quantized amounts directly, to prove the
        # __add__ operator — not Money.of — enforces 2dp half-even on its
        # output. 1.001 + 1.002 = 2.003 → 2.00.
        a = Money(Decimal("1.001"))
        b = Money(Decimal("1.002"))
        assert a + b == Money(Decimal("2.00"))

    def test_multiplication_by_decimal_returns_new_money(self) -> None:
        assert Money.of("299") * Decimal("0.90") == Money.of("269.10")

    def test_multiplication_result_is_quantized_half_even(self) -> None:
        # 299 * 1.00 * 0.90 * 0.85 = 228.735 -> half-even 2dp = 228.74
        product = Money.of("299") * Decimal("1.00") * Decimal("0.90") * Decimal("0.85")
        assert product == Money.of("228.74")

    def test_adding_different_currencies_raises(self) -> None:
        with pytest.raises(ValueError):
            _ = Money.of("1", "USD") + Money.of("1", "EUR")


class TestMoneyEquality:
    def test_two_monies_with_same_amount_and_currency_are_equal(self) -> None:
        assert Money.of("10") == Money.of("10")

    def test_monies_with_different_amounts_are_not_equal(self) -> None:
        assert Money.of("10") != Money.of("11")

    def test_monies_with_different_currencies_are_not_equal(self) -> None:
        assert Money.of("10", "USD") != Money.of("10", "EUR")

    def test_money_is_hashable(self) -> None:
        # frozen dataclass => usable in sets/dicts. Business need: keying by price.
        assert {Money.of("10"), Money.of("10")} == {Money.of("10")}
