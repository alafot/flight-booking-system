"""Integration tests for ``POST /bookings`` quote-trust contract (step 06-03).

ADR-006 (KPI-T1): when a commit carries a ``quoteId``, the BookingService
charges exactly ``quote.price_breakdown.total`` and references that same
quote in the BookingCommitted audit event. Demand changes between quote
and commit MUST NOT influence the charged amount — the traveler was shown
a price, the traveler pays that price.

These tests drive the contract end-to-end through the real HTTP route:

  * Valid quote in TTL → booking total_charged == quote.total.
  * Expired quote → 410 Gone, body cites "quote expired".
  * Unknown quote id → 404 Not Found, body cites "quote not found".
  * No quoteId at all → walking-skeleton path still works (backward compat).
  * Demand jump inside TTL → charged amount locked to pre-jump quote.
  * Audit replay confirms non-WS BookingCommitted events reconcile with
    their QuoteCreated parents.

All tests use ``build_test_container`` (Strategy A: FrozenClock +
InMemoryAuditLog) so TTL advances are deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus


# Frozen clock used across the whole file — deterministic baseline for TTL math.
_CLOCK = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
# Departure chosen 38 days after the clock, on a TUE, so time_multiplier=0.90
# and day_multiplier=0.85 — matches milestone-06 background pricing inputs.
_DEPARTURE = datetime(2026, 6, 2, 8, 0, tzinfo=UTC)
_FLIGHT_ID = "FL-QT-06-03"
_QUOTED_SEAT = "12C"
_CABIN_SIZE = 100


def _make_cabin(*, blocked_count: int = 0) -> Cabin:
    """Build a 100-seat cabin with seat 12C AVAILABLE.

    ``blocked_count`` flips the first N fillers to BLOCKED — used by the
    demand-jump scenario to mutate occupancy between quote and commit.
    """
    cabin = Cabin()
    cabin.seats[SeatId(_QUOTED_SEAT)] = Seat(
        id=SeatId(_QUOTED_SEAT),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    for index in range(1, _CABIN_SIZE):
        seat_id = SeatId(f"FILL-{index:03d}")
        status = (
            SeatStatus.BLOCKED if index <= blocked_count else SeatStatus.AVAILABLE
        )
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=status,
        )
    return cabin


def _seed_flight(
    container: Container, *, base_fare: str = "299", blocked_count: int = 0
) -> None:
    flight = Flight(
        id=FlightId(_FLIGHT_ID),
        origin="LAX",
        destination="NYC",
        departure_at=_DEPARTURE,
        arrival_at=_DEPARTURE,
        airline="MOCK",
        base_fare=Money.of(base_fare),
        cabin=_make_cabin(blocked_count=blocked_count),
    )
    container.flight_repo.add(flight)


def _quote_payload() -> dict:
    return {
        "flightId": _FLIGHT_ID,
        "seatIds": [_QUOTED_SEAT],
        "passengers": 1,
    }


def _booking_payload(*, quote_id: str | None = None, seat_id: str = _QUOTED_SEAT) -> dict:
    body = {
        "flightId": _FLIGHT_ID,
        "seatId": seat_id,
        "passenger": {"name": "Jane Doe"},
        "paymentToken": "mock-ok",
    }
    if quote_id is not None:
        body["quoteId"] = quote_id
    return body


@pytest.fixture
def container() -> Container:
    return build_test_container(now=_CLOCK, audit_path=None, deterministic_ids=True)


@pytest.fixture
def client(container: Container) -> TestClient:
    _seed_flight(container)
    return TestClient(create_app(container=container))


class TestCommitWithValidQuote:
    def test_commit_with_valid_unexpired_quote_charges_quoted_total(
        self, client: TestClient, container: Container
    ) -> None:
        # Create the quote. It locks the total at the current-state pricing
        # of the seeded flight.
        quote = client.post("/quotes", json=_quote_payload())
        assert quote.status_code == 200, quote.text
        quote_body = quote.json()
        quote_id = quote_body["quoteId"]
        quote_total = quote_body["total"]

        # Commit well within TTL (no clock advance needed).
        booking = client.post(
            "/bookings", json=_booking_payload(quote_id=quote_id)
        )

        assert booking.status_code == 201, booking.text
        body = booking.json()
        # Contract: total_charged == quote.total (not a recomputation).
        assert body["totalCharged"]["amount"] == quote_total
        assert body["totalCharged"]["currency"] == "USD"


class TestCommitExpiredOrUnknownQuote:
    def test_commit_after_quote_ttl_returns_410_gone(
        self, client: TestClient, container: Container
    ) -> None:
        quote = client.post("/quotes", json=_quote_payload())
        assert quote.status_code == 200
        quote_id = quote.json()["quoteId"]

        # Advance the frozen clock past the 30-minute window (31 minutes is
        # strictly > expires_at for a half-open TTL window).
        container.clock.advance(timedelta(minutes=31))

        response = client.post(
            "/bookings", json=_booking_payload(quote_id=quote_id)
        )

        assert response.status_code == 410, response.text
        assert "quote expired" in response.text

    def test_commit_with_unknown_quote_id_returns_404(
        self, client: TestClient, container: Container
    ) -> None:
        response = client.post(
            "/bookings", json=_booking_payload(quote_id="Q-DOES-NOT-EXIST")
        )

        assert response.status_code == 404, response.text
        assert "quote not found" in response.text


class TestCommitBackwardCompatibility:
    def test_commit_without_quote_id_still_works_walking_skeleton_path(
        self, client: TestClient, container: Container
    ) -> None:
        # No quoteId in the payload: the WS path charges base_fare (299.00
        # for this flight) and writes a BookingCommitted with the sentinel
        # "Q000-WS" quote id. This contract is intentional per ADR-006 so
        # existing walking-skeleton / seat-validation clients keep working.
        response = client.post("/bookings", json=_booking_payload())

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["totalCharged"]["amount"] == "299.00"
        # Sentinel event was still written — the audit trail never drops a
        # BookingCommitted.
        events = [
            e for e in container.audit.events if e.get("type") == "BookingCommitted"
        ]
        assert len(events) == 1
        assert events[0]["quote_id"] == "Q000-WS"
        assert events[0]["total_charged"] == "299.00"


class TestKpiT1DemandJumpDoesNotRecomputeTotal:
    def test_commit_honors_quoted_total_even_if_demand_jumps_mid_window(
        self, container: Container
    ) -> None:
        """KPI-T1 proof: the traveler is quoted at a given demand level; if
        demand spikes between quote and commit (simulated by BLOCKED seats
        filling the cabin), the charged amount MUST remain the quoted total.
        """
        # Seed a fresh flight with no blocked seats (0% effective occupancy).
        _seed_flight(container, blocked_count=0)
        client = TestClient(create_app(container=container))

        # Quote locks in the pre-jump total.
        quote = client.post("/quotes", json=_quote_payload())
        assert quote.status_code == 200, quote.text
        quote_body = quote.json()
        quote_id = quote_body["quoteId"]
        locked_total = Decimal(quote_body["total"])

        # Mutate the flight so occupancy jumps into the 86%+ bracket. If
        # BookingService re-priced at commit, demand_multiplier would jump
        # to 1.60 and the charged amount would be strictly higher.
        flight = container.flight_repo.get(FlightId(_FLIGHT_ID))
        assert flight is not None
        # Flip 86 fillers to BLOCKED → occupancy = 86/100 = 86%.
        flipped = 0
        for seat_id, seat in list(flight.cabin.seats.items()):
            if flipped >= 86:
                break
            if seat_id == SeatId(_QUOTED_SEAT):
                continue
            flight.cabin.seats[seat_id] = Seat(
                id=seat.id,
                seat_class=seat.seat_class,
                kind=seat.kind,
                status=SeatStatus.BLOCKED,
            )
            flipped += 1

        # Advance the clock INSIDE the 30-minute window.
        container.clock.advance(timedelta(minutes=20))

        # Compute what a naive re-price would charge (demand multiplier
        # jumps from 1.00 to 1.60 at 86%+, so the would-be re-price is
        # strictly greater than the quote).
        repriced_quote = client.post("/quotes", json=_quote_payload())
        repriced_total = Decimal(repriced_quote.json()["total"])
        assert repriced_total > locked_total, (
            f"expected re-priced total > locked total, got "
            f"repriced={repriced_total} vs locked={locked_total}"
        )

        # Commit with the ORIGINAL quote id.
        booking = client.post(
            "/bookings", json=_booking_payload(quote_id=quote_id)
        )

        assert booking.status_code == 201, booking.text
        charged = Decimal(booking.json()["totalCharged"]["amount"])
        # KPI-T1: charged amount equals locked total, not the mid-flight
        # re-priced total.
        assert charged == locked_total, (
            f"total drifted: charged={charged}, locked={locked_total}, "
            f"naive-repriced={repriced_total}"
        )
        # Audit trail reflects the locked total too (not a recomputation).
        booked_events = [
            e for e in container.audit.events if e.get("type") == "BookingCommitted"
        ]
        assert len(booked_events) == 1
        assert booked_events[0]["quote_id"] == quote_id
        assert Decimal(booked_events[0]["total_charged"]) == locked_total


class TestAuditReplayAfterStep0603:
    def test_audit_replay_verifies_non_ws_bookings_after_this_step(
        self, client: TestClient, container: Container
    ) -> None:
        """After step 06-03 the BookingCommitted event carries the REAL
        quote id (not Q000-WS), so the replay utility exercises a non-WS
        path and still reconciles cleanly.
        """
        from tests.support.audit_replay import verify_commits

        quote = client.post("/quotes", json=_quote_payload())
        assert quote.status_code == 200
        quote_id = quote.json()["quoteId"]

        booking = client.post(
            "/bookings", json=_booking_payload(quote_id=quote_id)
        )
        assert booking.status_code == 201

        events = list(container.audit.events)
        # There is one non-WS BookingCommitted event with a real quote id.
        booked = [e for e in events if e.get("type") == "BookingCommitted"]
        assert len(booked) == 1
        assert booked[0]["quote_id"] == quote_id, (
            f"expected real quote id {quote_id}, got {booked[0]['quote_id']!r}"
        )

        # Replay reconciles: the committed total equals the pricing-replay
        # of the matching QuoteCreated event inputs.
        mismatches = verify_commits(events)
        assert mismatches == [], f"audit replay mismatches: {mismatches!r}"
