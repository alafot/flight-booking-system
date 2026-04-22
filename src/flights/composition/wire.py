"""Composition root.

Builds application services from driven adapters. Two factory functions:
- ``build_production_container`` — real clock, real JSONL audit, real payment mock.
  (Still a RED scaffold — production path not needed yet; finished in a later step.)
- ``build_test_container`` — FrozenClock, InMemoryAuditLog, deterministic ids.

ADR-002: this is NOT FastAPI's DI container. Everything is instantiated manually
and returned as a ``Container`` dataclass. Tests use ``build_test_container``;
production uses ``build_production_container``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from flights.adapters.inmemory.booking_repository import InMemoryBookingRepository
from flights.adapters.inmemory.flight_repository import InMemoryFlightRepository
from flights.adapters.inmemory.quote_store import InMemoryQuoteStore
from flights.adapters.inmemory.seat_lock_store import InMemorySeatLockStore
from flights.adapters.mocks.audit import InMemoryAuditLog, JsonlAuditLog
from flights.adapters.mocks.clock import FrozenClock, SystemClock
from flights.adapters.mocks.email import MockEmailSender
from flights.adapters.mocks.ids import DeterministicIdGenerator, UuidIdGenerator
from flights.adapters.mocks.payment import MockPaymentGateway
from flights.application.booking_service import BookingService
from flights.application.quote_service import QuoteService
from flights.application.search_service import SearchService
from flights.application.seat_hold_service import SeatHoldService
from flights.application.seat_map_service import SeatMapService


@dataclass
class Container:
    flight_repo: InMemoryFlightRepository
    booking_repo: InMemoryBookingRepository
    quote_store: InMemoryQuoteStore
    seat_lock_store: InMemorySeatLockStore
    audit: InMemoryAuditLog | JsonlAuditLog
    clock: SystemClock | FrozenClock
    search_service: SearchService
    quote_service: QuoteService
    seat_hold_service: SeatHoldService
    seat_map_service: SeatMapService
    booking_service: BookingService


def build_production_container(audit_path: Path | None = None) -> Container:
    raise AssertionError("Not yet implemented — RED scaffold (build_production_container)")


def build_test_container(
    *,
    now: datetime,
    audit_path: Path | None = None,
    deterministic_ids: bool = True,
) -> Container:
    """Wire a container suitable for acceptance tests.

    Strategy A default: ``InMemoryAuditLog`` unless ``audit_path`` is given
    (then ``JsonlAuditLog``). Step 01-02 always uses ``InMemoryAuditLog``;
    the JSONL variant is covered by step 01-03's adapter-integration test.
    """
    flight_repo = InMemoryFlightRepository()
    booking_repo = InMemoryBookingRepository()
    quote_store = InMemoryQuoteStore()

    audit: InMemoryAuditLog | JsonlAuditLog = (
        JsonlAuditLog(audit_path) if audit_path is not None else InMemoryAuditLog()
    )
    clock = FrozenClock(now)
    ids: DeterministicIdGenerator | UuidIdGenerator = (
        DeterministicIdGenerator() if deterministic_ids else UuidIdGenerator()
    )
    # Route lock-id minting through the shared ``IdGenerator`` so acceptance
    # tests observe deterministic ``L001``/``L002``/... ids. Binding to the
    # bound-method keeps the sequence owned by the single ``ids`` instance.
    seat_lock_store = InMemorySeatLockStore(ids=ids.new_lock_id)
    payment = MockPaymentGateway()
    email = MockEmailSender()

    search_service = SearchService(flights=flight_repo, clock=clock)
    quote_service = QuoteService(
        flights=flight_repo,
        quotes=quote_store,
        audit=audit,
        clock=clock,
        ids=ids,
        bookings=booking_repo,
    )
    seat_hold_service = SeatHoldService(locks=seat_lock_store, clock=clock)
    seat_map_service = SeatMapService(
        flights=flight_repo,
        bookings=booking_repo,
        locks=seat_lock_store,
        clock=clock,
    )
    booking_service = BookingService(
        flights=flight_repo,
        bookings=booking_repo,
        quotes=quote_store,
        locks=seat_lock_store,
        payment=payment,
        email=email,
        audit=audit,
        clock=clock,
        ids=ids,
    )

    return Container(
        flight_repo=flight_repo,
        booking_repo=booking_repo,
        quote_store=quote_store,
        seat_lock_store=seat_lock_store,
        audit=audit,
        clock=clock,
        search_service=search_service,
        quote_service=quote_service,
        seat_hold_service=seat_hold_service,
        seat_map_service=seat_map_service,
        booking_service=booking_service,
    )
