"""BookingService.

Commit critical section (ADR-008). Step 01-03 implements the walking-skeleton
happy path: charge payment, build a confirmed ``Booking`` from the request,
persist it, queue a confirmation email and write a ``BookingCommitted``
audit event.

Deferred to later phases (DO NOT add here):
- Quote validation (``QuoteService`` body + ``quote_id`` lookup) — Phase 04.
- Seat-lock validation (``SeatLockStore.is_valid``) — Phase 07.
- Payment-failure branch + 410-gone for expired locks — Phases 06/07.
- Cancellation / modification flows — later slices.

Inline comments tag the callsites where those validations will slot in.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from flights.domain.model.booking import Booking, BookingStatus
from flights.domain.model.ids import BookingReference, FlightId, QuoteId, SeatId, SessionId
from flights.domain.model.passenger import PassengerDetails
from flights.domain.model.seat import SeatStatus
from flights.domain.ports import (
    AuditLog,
    BookingRepository,
    Clock,
    EmailSender,
    FlightRepository,
    IdGenerator,
    PaymentGateway,
    QuoteStore,
    SeatLockStore,
)

commit_lock = threading.RLock()


@dataclass
class CommitRequest:
    flight_id: FlightId
    seat_ids: tuple[SeatId, ...]
    passengers: tuple[PassengerDetails, ...]
    payment_token: str
    quote_id: QuoteId | None = None
    lock_id: str | None = None
    session_id: SessionId | None = None


@dataclass
class CommitResult:
    booking: Booking | None
    error_code: str | None = None
    error_message: str | None = None


class BookingService:
    def __init__(
        self,
        flights: FlightRepository,
        bookings: BookingRepository,
        quotes: QuoteStore,
        locks: SeatLockStore,
        payment: PaymentGateway,
        email: EmailSender,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._flights = flights
        self._bookings = bookings
        self._quotes = quotes
        self._locks = locks
        self._payment = payment
        self._email = email
        self._audit = audit
        self._clock = clock
        self._ids = ids

    def commit(self, request: CommitRequest) -> CommitResult:
        with commit_lock:
            flight = self._flights.get(request.flight_id)
            if flight is None:
                return CommitResult(
                    booking=None,
                    error_code="FLIGHT_NOT_FOUND",
                    error_message=f"flight {request.flight_id.value} not found",
                )

            # Phase 04: verify quote via self._quotes.get_valid(request.quote_id, now).
            # Phase 07: verify lock via self._locks.is_valid(request.lock_id, now).

            # Step 03-03: seat validation BEFORE charging payment. The three
            # branches below correspond to the three failure modes enumerated
            # in the milestone-03 feature: unknown seat (400), blocked seat
            # (409), and already-booked seat (409).
            seat_error = self._validate_seats(flight, request)
            if seat_error is not None:
                return seat_error

            total = flight.base_fare
            payment_result = self._payment.charge(request.payment_token, total)
            # Phase 06: handle payment_result.succeeded == False → PAYMENT_DECLINED branch.
            assert payment_result.succeeded, "payment failure path not yet implemented (Phase 06)"

            reference = self._ids.new_booking_reference()
            now = self._clock.now()
            quote_id = request.quote_id or QuoteId("Q000-WS")
            booking = Booking(
                reference=reference,
                flight_id=request.flight_id,
                seat_ids=request.seat_ids,
                passengers=request.passengers,
                total_charged=total,
                status=BookingStatus.CONFIRMED,
                quote_id=quote_id,
                confirmed_at=now,
            )
            self._bookings.save(booking)
            self._email.queue_confirmation(booking)
            self._audit.write(
                {
                    "type": "BookingCommitted",
                    "booking_reference": reference.value,
                    "flight_id": request.flight_id.value,
                    "seat_ids": [s.value for s in request.seat_ids],
                    "at": now.isoformat(),
                }
            )
            return CommitResult(booking=booking, error_code=None)

    def get(self, reference: BookingReference) -> Booking | None:
        return self._bookings.get(reference)

    def _validate_seats(
        self, flight: "object", request: CommitRequest
    ) -> CommitResult | None:
        """Validate every requested seat against the cabin and current bookings.

        Returns a ``CommitResult`` with the appropriate error code on the first
        failing seat, or ``None`` if all seats pass. Validation runs in this
        order for each seat: identity (unknown) -> status (blocked) -> conflict
        (already booked). Payment is not charged if any seat fails.
        """
        cabin_seats = flight.cabin.seats  # type: ignore[attr-defined]
        for seat_id in request.seat_ids:
            seat = cabin_seats.get(seat_id)
            if seat is None:
                return CommitResult(
                    booking=None,
                    error_code="UNKNOWN_SEAT",
                    error_message=f"unknown seat: {seat_id.value}",
                )
            if seat.status == SeatStatus.BLOCKED:
                return CommitResult(
                    booking=None,
                    error_code="SEAT_NOT_FOR_SALE",
                    error_message=f"seat not for sale: {seat_id.value}",
                )
            if self._seat_already_booked(request.flight_id, seat_id):
                return CommitResult(
                    booking=None,
                    error_code="SEAT_ALREADY_BOOKED",
                    error_message=f"seat already booked: {seat_id.value}",
                )
        return None

    def _seat_already_booked(self, flight_id: FlightId, seat_id: SeatId) -> bool:
        for existing in self._bookings.iter_all():
            if existing.flight_id != flight_id:
                continue
            if existing.status != BookingStatus.CONFIRMED:
                continue
            if seat_id in existing.seat_ids:
                return True
        return False
