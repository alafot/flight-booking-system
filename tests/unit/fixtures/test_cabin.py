"""Unit tests for the default-cabin fixture (ADR-004 layout).

``default_cabin()`` is a pure data-generation function — its public signature
is its driving port. Port-to-port at domain scope: we call it and assert on
the returned ``Cabin``.

Test budget
-----------
AC1-AC3 describe six distinct layout invariants:

1. Cabin has 180 seats (30 rows × 6 columns).
2. Row 1 A/F are FIRST + PRIVATE_SUITE (suite override over FRONT_ROW).
3. Row 5 columns are BUSINESS class.
4. Row 12 columns C/D are ECONOMY + AISLE kind.
5. Row 14 seats are EXIT_ROW (override over default kind).
6. Economy standard rows assign WINDOW/AISLE/MIDDLE per column position.

Budget: 6 behaviors × 2 = 12 unit tests. Actual: 6 tests (one per behavior,
with parametrization for column variations where it collapses cleanly).
"""

from __future__ import annotations

import pytest

from flights.domain.model.ids import SeatId
from flights.domain.model.seat import SeatClass, SeatKind, SeatStatus
from tests.fixtures.cabin import default_cabin


def test_default_cabin_has_180_seats() -> None:
    cabin = default_cabin()
    assert cabin.seat_count() == 180


def test_seat_1A_is_first_private_suite() -> None:
    cabin = default_cabin()
    seat_1a = cabin.seats[SeatId("1A")]
    seat_1f = cabin.seats[SeatId("1F")]
    assert seat_1a.seat_class is SeatClass.FIRST
    assert seat_1a.kind is SeatKind.PRIVATE_SUITE
    assert seat_1a.status is SeatStatus.AVAILABLE
    assert seat_1f.seat_class is SeatClass.FIRST
    assert seat_1f.kind is SeatKind.PRIVATE_SUITE


def test_seat_5C_is_business() -> None:
    cabin = default_cabin()
    seat = cabin.seats[SeatId("5C")]
    assert seat.seat_class is SeatClass.BUSINESS


def test_seat_12C_is_economy_aisle() -> None:
    # Column C is an aisle column in the economy standard layout.
    cabin = default_cabin()
    seat = cabin.seats[SeatId("12C")]
    assert seat.seat_class is SeatClass.ECONOMY
    assert seat.kind is SeatKind.AISLE


@pytest.mark.parametrize("column", ["A", "B", "C", "D", "E", "F"])
def test_row_14_seats_are_exit_row(column: str) -> None:
    cabin = default_cabin()
    seat = cabin.seats[SeatId(f"14{column}")]
    assert seat.kind is SeatKind.EXIT_ROW


@pytest.mark.parametrize(
    "column,expected_kind",
    [
        ("A", SeatKind.WINDOW),
        ("B", SeatKind.MIDDLE),
        ("C", SeatKind.AISLE),
        ("D", SeatKind.AISLE),
        ("E", SeatKind.MIDDLE),
        ("F", SeatKind.WINDOW),
    ],
)
def test_economy_window_aisle_middle_kinds_per_column(
    column: str, expected_kind: SeatKind
) -> None:
    # Row 20 is a plain economy row (not 14 exit row, not premium 7-10 band).
    cabin = default_cabin()
    seat = cabin.seats[SeatId(f"20{column}")]
    assert seat.seat_class is SeatClass.ECONOMY
    assert seat.kind is expected_kind
