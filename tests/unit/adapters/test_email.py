"""MockEmailSender — unit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from flights.adapters.mocks.email import MockEmailSender
from flights.domain.model.booking import Booking, BookingStatus
from flights.domain.model.ids import BookingReference, FlightId, QuoteId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.passenger import PassengerDetails


def _make_booking(reference: str) -> Booking:
    return Booking(
        reference=BookingReference(reference),
        flight_id=FlightId("FL-1"),
        seat_ids=(SeatId("12C"),),
        passengers=(PassengerDetails(full_name="Jane Doe"),),
        total_charged=Money(Decimal("299.00")),
        status=BookingStatus.CONFIRMED,
        quote_id=QuoteId("Q-1"),
        confirmed_at=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
    )


class TestMockEmailSenderQueueConfirmation:
    def test_queue_confirmation_appends_booking_to_queued_list(self) -> None:
        sender = MockEmailSender()
        booking = _make_booking("REF001")

        sender.queue_confirmation(booking)

        assert sender.queued == [booking]

    def test_multiple_queue_confirmations_preserve_order(self) -> None:
        sender = MockEmailSender()
        first = _make_booking("REF001")
        second = _make_booking("REF002")
        third = _make_booking("REF003")

        sender.queue_confirmation(first)
        sender.queue_confirmation(second)
        sender.queue_confirmation(third)

        assert sender.queued == [first, second, third]
