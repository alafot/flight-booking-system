"""Booking aggregate (scaffold)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from flights.domain.model.ids import BookingReference, FlightId, QuoteId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.passenger import PassengerDetails

__SCAFFOLD__ = True


class BookingStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_TRAVELER = "CANCELLED_BY_TRAVELER"
    CANCELLED_BY_OPERATOR = "CANCELLED_BY_OPERATOR"


@dataclass
class Booking:
    reference: BookingReference
    flight_id: FlightId
    seat_ids: tuple[SeatId, ...]
    passengers: tuple[PassengerDetails, ...]
    total_charged: Money
    status: BookingStatus
    quote_id: QuoteId
    confirmed_at: datetime
    history: list[str] = field(default_factory=list)
