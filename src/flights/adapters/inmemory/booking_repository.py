"""InMemoryBookingRepository.

Thread-safe. ``save`` is idempotent by reference — writing a booking with an
existing reference replaces the previous record (ADR-008).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from flights.domain.model.booking import Booking
from flights.domain.model.ids import BookingReference


class InMemoryBookingRepository:
    def __init__(self) -> None:
        self._bookings: dict[BookingReference, Booking] = {}
        self._lock = threading.RLock()

    def get(self, reference: BookingReference) -> Booking | None:
        with self._lock:
            return self._bookings.get(reference)

    def save(self, booking: Booking) -> None:
        with self._lock:
            self._bookings[booking.reference] = booking

    def iter_all(self) -> Iterable[Booking]:
        """Snapshot all stored bookings. Returns a tuple so callers may
        iterate without holding the repository lock.
        """
        with self._lock:
            return tuple(self._bookings.values())
