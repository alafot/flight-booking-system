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
from datetime import datetime

from flights.domain.model.booking import Booking, BookingStatus
from flights.domain.model.ids import BookingReference, FlightId, QuoteId, SeatId, SessionId
from flights.domain.model.passenger import PassengerDetails
from flights.domain.model.quote import Quote
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


@dataclass(frozen=True)
class _QuoteLookup:
    """Internal return type for :meth:`BookingService._resolve_quote`.

    Exactly one of ``quote`` or ``error`` is set when ``request.quote_id`` is
    present; both are None when no quote id was supplied (backward-compat
    walking-skeleton path). Captures the "expired vs unknown" distinction
    inside the service so the HTTP adapter maps a single error_code to the
    right status code.
    """

    quote: Quote | None = None
    error: CommitResult | None = None


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

            # Step 06-03: honor the quote's locked-in total (ADR-006 KPI-T1).
            # When ``request.quote_id`` is present we look up the quote and:
            #   * 404 if the id was never issued (``get`` returns None).
            #   * 410 if the id is known but past its 30-min TTL
            #     (``get_valid`` returns None but ``get`` returns a quote).
            #   * charge ``quote.price_breakdown.total`` — never recomputed
            #     from current flight state — when the quote is live.
            # Without a ``quote_id`` (walking-skeleton backward-compat path)
            # the service falls back to ``flight.base_fare`` as before.
            now = self._clock.now()
            quote_lookup = self._resolve_quote(request.quote_id, now)
            if quote_lookup.error is not None:
                return quote_lookup.error

            # Step 03-03: seat validation BEFORE charging payment. The three
            # branches below correspond to the three failure modes enumerated
            # in the milestone-03 feature: unknown seat (400), blocked seat
            # (409), and already-booked seat (409).
            seat_error = self._validate_seats(flight, request)
            if seat_error is not None:
                return seat_error

            # Step 07-02: seat-lock validation (ADR-008). When a ``lock_id``
            # is supplied, we enforce three invariants BEFORE charging:
            #   * lock exists and has not expired (410 otherwise).
            #   * lock exists at all (404 otherwise).
            #   * lock is owned by ``request.session_id`` (403 otherwise).
            # Backward-compat: a commit without ``lock_id`` skips this block
            # entirely — preserves the walking-skeleton and milestone-06
            # contract where commits charged directly without holding a lock.
            lock_error = self._validate_lock(request, now)
            if lock_error is not None:
                return lock_error

            total = (
                quote_lookup.quote.price_breakdown.total
                if quote_lookup.quote is not None
                else flight.base_fare
            )
            payment_result = self._payment.charge(request.payment_token, total)
            # Phase 06-02: payment-declined branch. When the gateway returns
            # succeeded=False we write a PaymentFailed audit event (so the
            # replay/forensic trail captures the attempt) and return a
            # PAYMENT_DECLINED result — mapped to HTTP 402 by the driving
            # adapter. No Booking is persisted; no confirmation email is
            # queued. The request.quote_id is carried through as-is (None
            # for the WS path, a real QuoteId once Phase 06-03 wires quote
            # look-up on commit).
            if not payment_result.succeeded:
                self._audit.write(
                    {
                        "type": "PaymentFailed",
                        "quote_id": (
                            request.quote_id.value
                            if request.quote_id is not None
                            else None
                        ),
                        "flight_id": request.flight_id.value,
                        "seat_ids": [s.value for s in request.seat_ids],
                        "payment_token": request.payment_token,
                        "reason": payment_result.reason or "declined",
                        "attempted_at": now.isoformat(),
                    }
                )
                return CommitResult(
                    booking=None,
                    error_code="PAYMENT_DECLINED",
                    error_message="payment declined by gateway",
                )

            reference = self._ids.new_booking_reference()
            # Step 06-03: carry the real quote id onto the booking when the
            # commit consumed a quote. The "Q000-WS" sentinel is the
            # walking-skeleton path (no quote) — audit replay skips it.
            quote_id = (
                quote_lookup.quote.id
                if quote_lookup.quote is not None
                else QuoteId("Q000-WS")
            )
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
            # Step 07-02: release the seat-lock on successful commit (ADR-008).
            # The lock existed only to reserve the seat between acquire and
            # commit; once the booking is persisted the seat is owned by the
            # booking itself and the lock is redundant. Releasing eagerly
            # means a subsequent attempt by any session finds the seat free
            # at the lock layer and fails instead at the booking layer
            # (SEAT_ALREADY_BOOKED via ``_seat_already_booked``).
            if request.lock_id is not None:
                self._locks.release(request.lock_id)
            # Phase 06-02: BookingCommitted carries quote_id and total_charged
            # so the replay utility (``tests/support/audit_replay.py``) can
            # reconcile the charged amount against the matching QuoteCreated
            # event. ``quote_id`` is the "Q000-WS" sentinel when the commit
            # ran without an upstream quote (walking-skeleton path); the
            # replay utility explicitly skips that sentinel.
            self._audit.write(
                {
                    "type": "BookingCommitted",
                    "booking_reference": reference.value,
                    "quote_id": quote_id.value,
                    "flight_id": request.flight_id.value,
                    "seat_ids": [s.value for s in request.seat_ids],
                    "total_charged": str(total.amount),
                    "at": now.isoformat(),
                }
            )
            return CommitResult(booking=booking, error_code=None)

    def get(self, reference: BookingReference) -> Booking | None:
        return self._bookings.get(reference)

    def _resolve_quote(
        self, quote_id: QuoteId | None, now: datetime
    ) -> _QuoteLookup:
        """Look up the request's quote and classify the three possible states.

        * No quote_id supplied → empty lookup (walking-skeleton path).
        * quote_id issued and still within TTL → ``quote`` populated.
        * quote_id issued but past ``expires_at`` → QUOTE_EXPIRED error (410).
        * quote_id never issued → QUOTE_NOT_FOUND error (404).

        The 410-vs-404 distinction uses two ``QuoteStore`` calls:
        ``get_valid`` enforces the TTL, ``get`` ignores it. If ``get_valid``
        returns None but ``get`` returns a quote, the only possible cause is
        TTL expiry — so we map that to QUOTE_EXPIRED. ``get`` returning None
        means the id was never seen, so we map that to QUOTE_NOT_FOUND.
        """
        if quote_id is None:
            return _QuoteLookup()
        valid = self._quotes.get_valid(quote_id, now)
        if valid is not None:
            return _QuoteLookup(quote=valid)
        raw = self._quotes.get(quote_id)
        if raw is None:
            return _QuoteLookup(
                error=CommitResult(
                    booking=None,
                    error_code="QUOTE_NOT_FOUND",
                    error_message=f"quote not found: {quote_id.value}",
                )
            )
        return _QuoteLookup(
            error=CommitResult(
                booking=None,
                error_code="QUOTE_EXPIRED",
                error_message=f"quote expired: {quote_id.value}",
            )
        )

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

    def _validate_lock(
        self, request: CommitRequest, now: datetime
    ) -> CommitResult | None:
        """Validate ``request.lock_id`` against the store (ADR-008).

        Mirrors the 410-vs-404 idiom used for quotes: call ``is_valid``
        first (TTL-enforcing), and only if that returns False do we call
        ``get`` to distinguish "stored but expired" from "never issued".
        Session-mismatch is a 403 regardless of TTL because attempting to
        use another session's lock — even one that would otherwise be
        live — is a policy violation, not a timing issue.

        Returns ``None`` when the commit should proceed, or a populated
        :class:`CommitResult` error otherwise.
        """
        if request.lock_id is None:
            return None
        if self._locks.is_valid(request.lock_id, now):
            return self._check_lock_session_ownership(request)
        raw = self._locks.get(request.lock_id)
        if raw is None:
            return CommitResult(
                booking=None,
                error_code="LOCK_NOT_FOUND",
                error_message=f"seat lock not found: {request.lock_id}",
            )
        return CommitResult(
            booking=None,
            error_code="LOCK_EXPIRED",
            error_message=f"seat lock expired: {request.lock_id}",
        )

    def _check_lock_session_ownership(
        self, request: CommitRequest
    ) -> CommitResult | None:
        """Enforce that the commit's session owns the referenced lock.

        Split out from :meth:`_validate_lock` so the TTL branch stays
        single-purpose (only emits LOCK_EXPIRED / LOCK_NOT_FOUND) and the
        ownership branch reads as its own policy check.
        """
        raw = self._locks.get(request.lock_id)
        if raw is None:
            return None
        owner_session = getattr(raw, "session_id", None)
        if request.session_id is None:
            return None
        if owner_session == request.session_id:
            return None
        return CommitResult(
            booking=None,
            error_code="LOCK_SESSION_MISMATCH",
            error_message="seat lock not owned by session",
        )
