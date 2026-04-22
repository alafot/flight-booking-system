"""Integration test for concurrent ``POST /seat-locks`` (step 07-02).

ADR-008 KPI: under 10 threads racing for the same seat, the check-then-install
critical section in :class:`InMemorySeatLockStore` must produce exactly one
winner and nine rejections with zero 500s. This is the "last-seat race"
primitive the full 100-trial harness builds on in step 07-03.

Thread synchronisation uses ``threading.Barrier(10)`` so all ten requests
launch at the same instant — without the barrier, the ThreadPoolExecutor's
scheduling would serialise the acquires and the test would pass trivially
without exercising the race. We repeat the trial ``_TRIALS`` times because
a single trial could pass by luck on a non-atomic implementation; ten
independent trials make the probability of a false-green negligible.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus


_NOW = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
_FLIGHT_ID = "FL-LAX-NYC-0800"
_SEAT_ID = "30F"
_TRIALS = 10
_THREADS = 10


def _build_client() -> tuple[TestClient, Container]:
    """Fresh container per trial so each trial races for an un-locked seat.

    Sharing the container across trials would mean trial #2 starts with the
    seat already locked by trial #1's winner, and the race wouldn't happen.
    """
    container = build_test_container(now=_NOW, audit_path=None, deterministic_ids=True)
    departure = datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC)
    cabin = Cabin()
    cabin.seats[SeatId(_SEAT_ID)] = Seat(
        id=SeatId(_SEAT_ID),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    flight = Flight(
        id=FlightId(_FLIGHT_ID),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of("299"),
        cabin=cabin,
    )
    container.flight_repo.add(flight)
    client = TestClient(create_app(container=container))
    return client, container


def _race_one_trial(client: TestClient) -> list[int]:
    barrier = threading.Barrier(_THREADS)

    def _acquire(session_id: str) -> int:
        barrier.wait()
        response = client.post(
            "/seat-locks",
            json={
                "flightId": _FLIGHT_ID,
                "seatIds": [_SEAT_ID],
                "sessionId": session_id,
            },
        )
        return response.status_code

    with ThreadPoolExecutor(max_workers=_THREADS) as pool:
        futures = [
            pool.submit(_acquire, f"S-{index:02d}") for index in range(_THREADS)
        ]
        return [future.result() for future in futures]


class TestConcurrentLockAcquire:
    def test_ten_concurrent_acquires_for_same_seat_yield_exactly_one_winner(
        self,
    ) -> None:
        """Ten concurrent acquires against one seat, repeated ``_TRIALS``
        times. Every trial MUST produce exactly one 201 and nine 409s;
        any 500 or a deviation from 1/9 indicates a broken critical
        section.
        """
        for trial in range(_TRIALS):
            client, _container = _build_client()
            statuses = _race_one_trial(client)

            winners = [s for s in statuses if s == 201]
            conflicts = [s for s in statuses if s == 409]
            errors = [s for s in statuses if s >= 500]

            assert len(winners) == 1, (
                f"trial {trial}: expected 1 winner, got {len(winners)} "
                f"(statuses={statuses})"
            )
            assert len(conflicts) == 9, (
                f"trial {trial}: expected 9 conflicts, got {len(conflicts)} "
                f"(statuses={statuses})"
            )
            assert len(errors) == 0, (
                f"trial {trial}: expected zero 5xx, got {errors} "
                f"(statuses={statuses})"
            )
