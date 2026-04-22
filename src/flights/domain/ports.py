"""Driven ports (Protocol classes). No I/O in this file; implementations live in adapters/."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, runtime_checkable

from flights.domain.model.booking import Booking
from flights.domain.model.flight import Flight
from flights.domain.model.ids import BookingReference, FlightId, QuoteId, SeatId, SessionId
from flights.domain.model.money import Money
from flights.domain.model.quote import Quote

__SCAFFOLD__ = True


@runtime_checkable
class FlightRepository(Protocol):
    def get(self, flight_id: FlightId) -> Flight | None: ...
    def search(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        airline: str | None = None,
    ) -> list[Flight]: ...
    def add(self, flight: Flight) -> None: ...


@runtime_checkable
class BookingRepository(Protocol):
    def get(self, reference: BookingReference) -> Booking | None: ...
    def save(self, booking: Booking) -> None: ...
    def iter_all(self) -> Iterable[Booking]: ...


@runtime_checkable
class QuoteStore(Protocol):
    def save(self, quote: Quote) -> None: ...
    def get_valid(self, quote_id: QuoteId, now: datetime) -> Quote | None: ...
    # ``get`` ignores TTL — exposes the raw saved quote so callers can
    # distinguish "expired" (stored but past expires_at) from "unknown"
    # (never saved). BookingService.commit uses both methods to map a
    # missing valid quote to the correct HTTP status (410 vs 404).
    def get(self, quote_id: QuoteId) -> Quote | None: ...


@runtime_checkable
class SeatLockStore(Protocol):
    def acquire(
        self,
        flight_id: FlightId,
        seat_ids: tuple[SeatId, ...],
        session_id: SessionId,
        now: datetime,
    ) -> object: ...
    def release(self, lock_id: str) -> None: ...
    def is_valid(self, lock_id: str, now: datetime) -> bool: ...


class PaymentResult(Protocol):
    @property
    def succeeded(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...


@runtime_checkable
class PaymentGateway(Protocol):
    def charge(self, token: str, amount: Money) -> PaymentResult: ...


@runtime_checkable
class EmailSender(Protocol):
    def queue_confirmation(self, booking: Booking) -> None: ...


@runtime_checkable
class AuditLog(Protocol):
    def write(self, event: dict) -> None: ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    def new_booking_reference(self) -> BookingReference: ...
    def new_quote_id(self) -> QuoteId: ...
    def new_lock_id(self) -> str: ...
    def new_session_id(self) -> SessionId: ...
