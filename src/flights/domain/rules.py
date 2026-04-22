"""Business rule engine — pure functions (scaffold).

ADR-005: kept pure. Clocks are injected as `now` parameters.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from flights.domain.model.flight import Flight

__SCAFFOLD__ = True

MIN_BOOKING_LEAD_TIME = timedelta(hours=2)
MAX_ADVANCE_BOOKING = timedelta(days=11 * 30)  # approximate 11 months
MAX_PASSENGERS_PER_BOOKING = 9
CAPACITY_CEILING_PCT = Decimal("95")


def can_book(flight: Flight, now: datetime) -> bool:
    raise AssertionError("Not yet implemented — RED scaffold (rules.can_book)")


def advance_booking_ok(now: datetime, departure: datetime) -> bool:
    raise AssertionError("Not yet implemented — RED scaffold (rules.advance_booking_ok)")


def within_min_booking_lead_time(now: datetime, departure: datetime) -> bool:
    raise AssertionError("Not yet implemented — RED scaffold (rules.within_min_booking_lead_time)")


def capacity_ok(occupancy_pct: Decimal) -> bool:
    raise AssertionError("Not yet implemented — RED scaffold (rules.capacity_ok)")


def cancellation_fee_percent(now: datetime, departure: datetime) -> Decimal:
    raise AssertionError("Not yet implemented — RED scaffold (rules.cancellation_fee_percent)")
