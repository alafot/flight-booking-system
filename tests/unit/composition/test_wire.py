"""Composition root test — verifies ``build_test_container`` wires all ports and services.

Port-to-port: the driving port here is ``build_test_container``; the observable
outcome is the returned ``Container`` dataclass with every field populated with a
correctly typed, non-None collaborator. Services are inspected only for their
``__init__``-time wiring — method bodies remain scaffolded per step 01-02 scope.
"""

from __future__ import annotations

from datetime import UTC, datetime

from flights.adapters.inmemory.booking_repository import InMemoryBookingRepository
from flights.adapters.inmemory.flight_repository import InMemoryFlightRepository
from flights.adapters.inmemory.quote_store import InMemoryQuoteStore
from flights.adapters.inmemory.seat_lock_store import InMemorySeatLockStore
from flights.adapters.mocks.audit import InMemoryAuditLog
from flights.adapters.mocks.clock import FrozenClock
from flights.application.booking_service import BookingService
from flights.application.quote_service import QuoteService
from flights.application.search_service import SearchService
from flights.application.seat_hold_service import SeatHoldService
from flights.application.seat_map_service import SeatMapService
from flights.composition.wire import build_test_container


class TestBuildTestContainer:
    def test_returns_container_with_all_ports_and_services_wired(self) -> None:
        now = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)

        container = build_test_container(now=now, audit_path=None, deterministic_ids=True)

        # Driven ports / stores
        assert isinstance(container.flight_repo, InMemoryFlightRepository)
        assert isinstance(container.booking_repo, InMemoryBookingRepository)
        assert isinstance(container.quote_store, InMemoryQuoteStore)
        assert isinstance(container.seat_lock_store, InMemorySeatLockStore)
        assert isinstance(container.audit, InMemoryAuditLog)

        # Clock is frozen at the requested instant
        assert isinstance(container.clock, FrozenClock)
        assert container.clock.now() == now

        # Application services instantiated (constructors only — bodies remain scaffolded)
        assert isinstance(container.search_service, SearchService)
        assert isinstance(container.quote_service, QuoteService)
        assert isinstance(container.seat_hold_service, SeatHoldService)
        assert isinstance(container.seat_map_service, SeatMapService)
        assert isinstance(container.booking_service, BookingService)
