"""Seat, SeatClass, SeatKind (scaffold)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flights.domain.model.ids import SeatId

__SCAFFOLD__ = True


class SeatClass(StrEnum):
    ECONOMY = "ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"
    # PREMIUM_ECONOMY deferred — ADR-007


class SeatKind(StrEnum):
    STANDARD = "STANDARD"
    MIDDLE = "MIDDLE"
    AISLE = "AISLE"
    WINDOW = "WINDOW"
    EXIT_ROW = "EXIT_ROW"
    FRONT_SECTION = "FRONT_SECTION"
    BULKHEAD = "BULKHEAD"
    LIE_FLAT_SUITE = "LIE_FLAT_SUITE"
    WINDOW_SUITE = "WINDOW_SUITE"
    AISLE_ACCESS = "AISLE_ACCESS"
    PRIVATE_SUITE = "PRIVATE_SUITE"
    FRONT_ROW = "FRONT_ROW"


class SeatStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Seat:
    id: SeatId
    seat_class: SeatClass
    kind: SeatKind
    status: SeatStatus = SeatStatus.AVAILABLE
