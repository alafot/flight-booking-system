"""ID types (scaffold)."""

from __future__ import annotations

from dataclasses import dataclass

__SCAFFOLD__ = True


@dataclass(frozen=True, slots=True)
class FlightId:
    value: str


@dataclass(frozen=True, slots=True)
class SeatId:
    value: str


@dataclass(frozen=True, slots=True)
class BookingReference:
    value: str


@dataclass(frozen=True, slots=True)
class QuoteId:
    value: str


@dataclass(frozen=True, slots=True)
class SessionId:
    value: str
