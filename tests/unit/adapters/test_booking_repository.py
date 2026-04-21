"""InMemoryBookingRepository — unit tests.

Port-to-port at driven-port scope: ``save`` and ``get`` only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from flights.adapters.inmemory.booking_repository import InMemoryBookingRepository
from flights.domain.model.booking import Booking, BookingStatus
from flights.domain.model.ids import BookingReference, FlightId, QuoteId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.passenger import PassengerDetails


def _make_booking(reference: str, *, total: str = "299.00") -> Booking:
    return Booking(
        reference=BookingReference(reference),
        flight_id=FlightId("FL-1"),
        seat_ids=(SeatId("12C"),),
        passengers=(PassengerDetails(full_name="Jane Doe"),),
        total_charged=Money(Decimal(total)),
        status=BookingStatus.CONFIRMED,
        quote_id=QuoteId("Q-1"),
        confirmed_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
    )


class TestInMemoryBookingRepositorySaveAndGet:
    def test_get_returns_booking_after_save(self) -> None:
        repo = InMemoryBookingRepository()
        booking = _make_booking("REF001")

        repo.save(booking)

        assert repo.get(BookingReference("REF001")) is booking

    def test_get_returns_none_for_unknown_reference(self) -> None:
        repo = InMemoryBookingRepository()
        assert repo.get(BookingReference("MISSING")) is None

    def test_save_same_reference_replaces_previous_booking(self) -> None:
        repo = InMemoryBookingRepository()
        first = _make_booking("REF001", total="100.00")
        second = _make_booking("REF001", total="200.00")

        repo.save(first)
        repo.save(second)

        assert repo.get(BookingReference("REF001")) is second
