"""Integration tests for ``POST /quotes``.

These tests exercise the FastAPI quote route end-to-end through ``TestClient``
against the real ``build_test_container``. They cover:

  * Happy path (Appendix B example 1): total + full multiplier breakdown.
  * Quote identifier and 30-minute expiry stamp are present on the response.
  * A ``QuoteCreated`` audit event is written with the contract Phase 06 replays.
  * Unknown flight → 404.
  * Already-departed flight → 400.

Occupancy is driven by cabin state (OCCUPIED/BLOCKED seats in the cabin +
active CONFIRMED bookings). The tests seed a 100-seat cabin where ``N`` seats
are OCCUPIED so the computed pct lands in the expected demand bucket.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus


def _make_cabin(total: int, occupied: int, quote_seat_id: str) -> Cabin:
    """Build a cabin with ``total`` seats, ``occupied`` of which are OCCUPIED.

    The quoted seat (``quote_seat_id``) is always AVAILABLE. All seats are
    ECONOMY STANDARD — surcharges are out of scope for this step.
    """
    cabin = Cabin()
    # The quoted seat goes first, AVAILABLE.
    quoted = Seat(
        id=SeatId(quote_seat_id),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    cabin.seats[quoted.id] = quoted
    # Fill the rest: first ``occupied`` remaining seats are OCCUPIED,
    # the rest are AVAILABLE.
    for i in range(1, total):
        seat_id = SeatId(f"FILL-{i:03d}")
        status = SeatStatus.OCCUPIED if i <= occupied else SeatStatus.AVAILABLE
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=status,
        )
    return cabin


def _seed_flight(
    container: Container,
    *,
    flight_id: str,
    departure: datetime,
    occupied_seats: int,
    cabin_size: int,
    quote_seat_id: str,
    fare: str = "299",
) -> Flight:
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of(fare),
        cabin=_make_cabin(cabin_size, occupied_seats, quote_seat_id),
    )
    container.flight_repo.add(flight)
    return flight


@pytest.fixture
def appendix_b_example_1_client() -> TestClient:
    """Clock 2026-05-03, Tuesday departure 2026-06-02 (30 days), 0% occupancy.

    Expected: 299 × 1.00 × 0.90 × 0.85 = 228.735 → 228.74 USD.
    """
    now = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
    container = build_test_container(now=now, audit_path=None, deterministic_ids=True)
    _seed_flight(
        container,
        flight_id="FL-TUE-30D",
        departure=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),  # Tuesday
        occupied_seats=0,
        cabin_size=100,
        quote_seat_id="12C",
    )
    return TestClient(create_app(container=container))


class TestQuoteEndpointAppendixB:
    def test_quote_endpoint_returns_total_and_breakdown_for_appendix_b_example_1(
        self, appendix_b_example_1_client: TestClient
    ) -> None:
        response = appendix_b_example_1_client.post(
            "/quotes",
            json={
                "flightId": "FL-TUE-30D",
                "seatIds": ["12C"],
                "passengers": 1,
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        # Money is carried as string to preserve Decimal precision over JSON.
        assert body["total"] == "228.74"
        assert body["currency"] == "USD"
        assert body["demandMultiplier"] == "1.00"
        assert body["timeMultiplier"] == "0.90"
        assert body["dayMultiplier"] == "0.85"

    def test_quote_endpoint_returns_quote_id_and_expires_at(
        self, appendix_b_example_1_client: TestClient
    ) -> None:
        response = appendix_b_example_1_client.post(
            "/quotes",
            json={
                "flightId": "FL-TUE-30D",
                "seatIds": ["12C"],
                "passengers": 1,
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        # DeterministicIdGenerator seeds "Q001" first — the ID contract is
        # observable to callers so they can commit against it later.
        assert body["quoteId"] == "Q001"
        # TTL is exactly 30 minutes from the frozen clock (2026-05-03 10:00 UTC).
        assert body["expiresAt"] == "2026-05-03T10:30:00+00:00"


class TestQuoteEndpointAuditEvent:
    def test_quote_endpoint_writes_quote_created_audit_event(self) -> None:
        now = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
        container = build_test_container(
            now=now, audit_path=None, deterministic_ids=True
        )
        _seed_flight(
            container,
            flight_id="FL-AUDIT",
            departure=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
            occupied_seats=0,
            cabin_size=100,
            quote_seat_id="12C",
        )
        client = TestClient(create_app(container=container))

        response = client.post(
            "/quotes",
            json={"flightId": "FL-AUDIT", "seatIds": ["12C"], "passengers": 1},
        )
        assert response.status_code == 200, response.text

        # Audit log contract for Phase 06 replay:
        events = [e for e in container.audit.events if e.get("type") == "QuoteCreated"]
        assert len(events) == 1
        event = events[0]
        assert event["quote_id"] == "Q001"
        assert event["flight_id"] == "FL-AUDIT"
        assert event["seat_ids"] == ["12C"]
        # The event captures the pricing inputs so the replay check is unambiguous.
        assert event["occupancy_pct"] == "0"
        assert event["days_before_departure"] == 30
        assert event["departure_dow"] == "TUE"
        assert event["base_fare"] == "299.00"
        assert event["total"] == "228.74"
        assert event["created_at"] == "2026-05-03T10:00:00+00:00"
        assert event["expires_at"] == "2026-05-03T10:30:00+00:00"
        # session_id is always present — generated if not supplied.
        assert "session_id" in event


class TestQuoteEndpointErrorBranches:
    def test_quote_endpoint_for_unknown_flight_returns_404(self) -> None:
        now = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
        container = build_test_container(
            now=now, audit_path=None, deterministic_ids=True
        )
        client = TestClient(create_app(container=container))

        response = client.post(
            "/quotes",
            json={
                "flightId": "DOES-NOT-EXIST",
                "seatIds": ["12C"],
                "passengers": 1,
            },
        )

        assert response.status_code == 404, response.text

    def test_quote_endpoint_for_already_departed_flight_returns_400(self) -> None:
        now = datetime(2026, 6, 3, 10, 0, tzinfo=UTC)  # one day AFTER departure
        container = build_test_container(
            now=now, audit_path=None, deterministic_ids=True
        )
        _seed_flight(
            container,
            flight_id="FL-DEPARTED",
            departure=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),
            occupied_seats=0,
            cabin_size=100,
            quote_seat_id="12C",
        )
        client = TestClient(create_app(container=container))

        response = client.post(
            "/quotes",
            json={
                "flightId": "FL-DEPARTED",
                "seatIds": ["12C"],
                "passengers": 1,
            },
        )

        assert response.status_code == 400, response.text
