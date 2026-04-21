"""QuoteService — application layer orchestrator for POST /quotes.

Per ADR-006 the QuoteService builds ``PricingInputs`` from current flight
state plus the frozen clock, invokes the pure pricing function, persists the
resulting ``Quote`` (30-minute TTL), writes an audit event and returns the
quote to the driving adapter.

This step (04-02) wires the pricing engine — quote TTL enforcement on commit
and session-binding live in Phase 06.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from flights.domain import pricing
from flights.domain.model.booking import BookingStatus
from flights.domain.model.flight import Flight
from flights.domain.model.ids import FlightId, SeatId, SessionId
from flights.domain.model.money import Money
from flights.domain.model.quote import PriceBreakdown, Quote, SeatSurchargeLine
from flights.domain.model.seat import SeatStatus
from flights.domain.ports import (
    AuditLog,
    BookingRepository,
    Clock,
    FlightRepository,
    IdGenerator,
    QuoteStore,
)
from flights.domain.pricing import DayOfWeek, PricingInputs

QUOTE_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class QuoteRequest:
    flight_id: FlightId
    seat_ids: tuple[SeatId, ...]
    passengers: int
    session_id: SessionId | None = None


class QuoteNotFound(Exception):
    """Raised when the requested flight does not exist."""


class FlightAlreadyDeparted(Exception):
    """Raised when the requested flight's departure is in the past (per the Clock)."""


class QuoteService:
    def __init__(
        self,
        flights: FlightRepository,
        quotes: QuoteStore,
        audit: AuditLog,
        clock: Clock,
        ids: IdGenerator,
        bookings: BookingRepository,
    ) -> None:
        self._flights = flights
        self._quotes = quotes
        self._audit = audit
        self._clock = clock
        self._ids = ids
        self._bookings = bookings

    def quote(self, request: QuoteRequest) -> Quote:
        flight = self._flights.get(request.flight_id)
        if flight is None:
            raise QuoteNotFound(f"flight {request.flight_id.value} not found")

        now = self._clock.now()
        days_before = (flight.departure_at.date() - now.date()).days
        if days_before < 0:
            raise FlightAlreadyDeparted(
                f"flight {request.flight_id.value} already departed at "
                f"{flight.departure_at.isoformat()}"
            )

        occupancy_pct = self._occupancy_pct(flight)
        departure_dow = DayOfWeek(flight.departure_at.weekday())
        surcharges = self._seat_surcharges(flight, request.seat_ids)
        taxes = self._compute_taxes(
            flight=flight,
            occupancy_pct=occupancy_pct,
            days_before=days_before,
            departure_dow=departure_dow,
            surcharges=surcharges,
        )
        fees = pricing.lookup_flat_fees(flight.id.value)
        breakdown = pricing.price(
            PricingInputs(
                base_fare=flight.base_fare,
                occupancy_pct=occupancy_pct,
                days_before_departure=days_before,
                departure_dow=departure_dow,
                surcharges=surcharges,
                taxes=taxes,
                fees=fees,
            )
        )

        session = request.session_id or self._ids.new_session_id()
        quote_id = self._ids.new_quote_id()
        expires_at = now + QUOTE_TTL
        quote = Quote(
            id=quote_id,
            session_id=session,
            flight_id=request.flight_id,
            seat_ids=request.seat_ids,
            passengers=request.passengers,
            price_breakdown=breakdown,
            created_at=now,
            expires_at=expires_at,
        )
        self._quotes.save(quote)
        self._audit.write(
            self._build_audit_event(
                quote=quote,
                breakdown=breakdown,
                occupancy_pct=occupancy_pct,
                days_before=days_before,
                departure_dow=departure_dow,
            )
        )
        return quote

    def _occupancy_pct(self, flight: Flight) -> Decimal:
        """Current-state occupancy = (cabin-OCCUPIED + cabin-BLOCKED + active
        CONFIRMED bookings on this flight) / cabin size × 100.

        Seat locks are Phase 07 and are not counted here. If the cabin has
        no seats (minimal walking-skeleton flight), occupancy is 0 — the
        base fare stands with demand multiplier 1.00.
        """
        total = flight.cabin.seat_count()
        if total == 0:
            return Decimal("0")
        cabin_occupied = sum(
            1
            for seat in flight.cabin.seats.values()
            if seat.status in (SeatStatus.OCCUPIED, SeatStatus.BLOCKED)
        )
        booked = self._active_booked_seat_count(flight.id)
        return Decimal(cabin_occupied + booked) / Decimal(total) * Decimal(100)

    @staticmethod
    def _compute_taxes(
        *,
        flight: Flight,
        occupancy_pct: Decimal,
        days_before: int,
        departure_dow: DayOfWeek,
        surcharges: tuple[SeatSurchargeLine, ...],
    ) -> Money:
        """Build the taxable base and apply the route's tax rate (step 05-02).

        Taxable base = ``base × demand × time × day + Σ surcharges`` held at
        full Decimal precision — rounding is deferred to Money.of inside
        ``compute_taxes`` so the applied rate sees the same number the
        multipliers produced (not a pre-rounded cent value).
        """
        demand = pricing._demand_multiplier(occupancy_pct)
        time = pricing._time_multiplier(days_before)
        dow = pricing._day_multiplier(departure_dow)
        taxable_amount = flight.base_fare.amount * demand * time * dow
        for line in surcharges:
            taxable_amount += line.amount.amount
        taxable_base = Money(taxable_amount, flight.base_fare.currency)
        return pricing.compute_taxes(taxable_base, flight.route_kind)

    @staticmethod
    def _seat_surcharges(
        flight: Flight, seat_ids: tuple[SeatId, ...]
    ) -> tuple[SeatSurchargeLine, ...]:
        """Compute per-seat surcharge lines from the cabin's (class, kind) map.

        A seat requested that isn't in the cabin is skipped silently here; the
        downstream ``BookingService.commit`` validates seat membership and
        returns UNKNOWN_SEAT with a 400. Pricing is advisory — a quote for an
        unknown seat still returns a breakdown, the commit fails.
        """
        lines: list[SeatSurchargeLine] = []
        for seat_id in seat_ids:
            seat = flight.cabin.seats.get(seat_id)
            if seat is None:
                continue
            amount = pricing.lookup_seat_surcharge(seat.seat_class, seat.kind)
            lines.append(SeatSurchargeLine(seat=seat_id, amount=amount))
        return tuple(lines)

    def _active_booked_seat_count(self, flight_id: FlightId) -> int:
        count = 0
        for booking in self._bookings.iter_all():
            if booking.flight_id != flight_id:
                continue
            if booking.status != BookingStatus.CONFIRMED:
                continue
            count += len(booking.seat_ids)
        return count

    @staticmethod
    def _build_audit_event(
        *,
        quote: Quote,
        breakdown: PriceBreakdown,
        occupancy_pct: Decimal,
        days_before: int,
        departure_dow: DayOfWeek,
    ) -> dict:
        """Serialise the QuoteCreated event.

        Phase 06's audit-replay check will compare against this exact shape:
        any addition must preserve the listed keys.
        """
        return {
            "type": "QuoteCreated",
            "quote_id": quote.id.value,
            "session_id": quote.session_id.value,
            "flight_id": quote.flight_id.value,
            "seat_ids": [s.value for s in quote.seat_ids],
            "occupancy_pct": str(occupancy_pct),
            "days_before_departure": days_before,
            "departure_dow": departure_dow.name,
            "base_fare": str(breakdown.base_fare.amount),
            "total": str(breakdown.total.amount),
            "created_at": quote.created_at.isoformat(),
            "expires_at": quote.expires_at.isoformat(),
        }
