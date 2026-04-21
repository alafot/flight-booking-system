"""Default 30x6 cabin fixture (ADR-004).

``default_cabin()`` builds the canonical 180-seat cabin used across the
flight-booking scenarios. Seat class is determined by row band, and seat
kind encodes the pricing-relevant layout:

Class bands
    rows 1-2   -> FIRST
    rows 3-6   -> BUSINESS
    rows 7-30  -> ECONOMY

Kind layout
    row 1       -> FRONT_ROW, with A/F overridden to PRIVATE_SUITE
    row 2       -> FRONT_ROW (all columns)
    row 3       -> A/F = WINDOW_SUITE, B/E = LIE_FLAT_SUITE, C/D = AISLE_ACCESS
    rows 4-6    -> A/F = WINDOW, B/E = MIDDLE, C/D = AISLE (business standard)
    rows 7-30   -> A/F = WINDOW, B/E = MIDDLE, C/D = AISLE (economy standard)
    row 14      -> EXIT_ROW for every column (overrides the economy default)

The factory is a pure data-generation function whose public signature
(``default_cabin() -> Cabin``) is itself its driving port.
"""

from __future__ import annotations

from flights.domain.model.flight import Cabin
from flights.domain.model.ids import SeatId
from flights.domain.model.seat import Seat, SeatClass, SeatKind

TOTAL_ROWS = 30
COLUMNS: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")
WINDOW_COLUMNS = frozenset({"A", "F"})
MIDDLE_COLUMNS = frozenset({"B", "E"})
AISLE_COLUMNS = frozenset({"C", "D"})
EXIT_ROW_NUMBER = 14


def _class_for_row(row: int) -> SeatClass:
    if row <= 2:
        return SeatClass.FIRST
    if row <= 6:
        return SeatClass.BUSINESS
    return SeatClass.ECONOMY


def _standard_kind_by_column(column: str) -> SeatKind:
    if column in WINDOW_COLUMNS:
        return SeatKind.WINDOW
    if column in AISLE_COLUMNS:
        return SeatKind.AISLE
    return SeatKind.MIDDLE


def _business_row_3_kind(column: str) -> SeatKind:
    if column in WINDOW_COLUMNS:
        return SeatKind.WINDOW_SUITE
    if column in AISLE_COLUMNS:
        return SeatKind.AISLE_ACCESS
    return SeatKind.LIE_FLAT_SUITE


def _kind_for(row: int, column: str) -> SeatKind:
    if row == 1:
        return SeatKind.PRIVATE_SUITE if column in WINDOW_COLUMNS else SeatKind.FRONT_ROW
    if row == 2:
        return SeatKind.FRONT_ROW
    if row == 3:
        return _business_row_3_kind(column)
    if row == EXIT_ROW_NUMBER:
        return SeatKind.EXIT_ROW
    # Rows 4-6 (business standard) and 7-30 (economy standard, except 14).
    return _standard_kind_by_column(column)


def default_cabin() -> Cabin:
    cabin = Cabin()
    for row in range(1, TOTAL_ROWS + 1):
        seat_class = _class_for_row(row)
        for column in COLUMNS:
            seat_id = SeatId(f"{row}{column}")
            cabin.seats[seat_id] = Seat(
                id=seat_id,
                seat_class=seat_class,
                kind=_kind_for(row, column),
            )
    return cabin
