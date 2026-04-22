"""Race-last-seat harness (KPI-T2).

Runs N trials, each spawning T threads that race for a single available seat
via ``POST /seat-locks``. Every trial must produce exactly ONE winner and
nine rejections — ZERO trials may have more than one winner (a
double-booking, which fails KPI-T2).

Usage::

    python scripts/race_last_seat.py                     # 100 trials × 10 threads
    python scripts/race_last_seat.py --trials 50         # override trial count

On perfect runs the script prints a single JSON object and exits 0. If ANY
trial produces >1 winner, it prints the summary and exits 1 so CI can fail
the merge gate.

Design notes
------------
* Each trial builds a FRESH ``Container`` + ``TestClient``. Resetting per-trial
  guarantees no cross-trial state leakage — the flight, lock store, audit log
  all start empty. This mirrors a cold-start production deploy 100×.
* Threads synchronise on a ``threading.Barrier`` so all T lock requests fire
  within microseconds of one another, maximising contention on the critical
  section the ADR-008 lock is designed to protect.
* The harness is imported by ``tests/e2e/test_race_last_seat.py`` and by the
  acceptance step "the race-last-seat harness runs 100 trials …". Keeping one
  implementation avoids drift between the CLI and CI tests.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.composition.wire import build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus

# Flight / seat under test — the harness seeds exactly this cabin, one seat.
_FLIGHT_ID = "FL-TEST"
_SEAT_ID = "30F"
_TRIAL_CLOCK = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


def _seed_single_seat_flight() -> tuple:
    """Build a fresh (container, app) pair with ONE AVAILABLE seat.

    Returns the container so callers can inspect it post-race if needed, and
    the FastAPI app so the caller can drive it via ``TestClient``.
    """
    container = build_test_container(
        now=_TRIAL_CLOCK,
        audit_path=None,
        deterministic_ids=True,
    )
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
        departure_at=_TRIAL_CLOCK,
        arrival_at=_TRIAL_CLOCK,
        airline="MOCK",
        base_fare=Money.of("299"),
        cabin=cabin,
    )
    container.flight_repo.add(flight)
    app = create_app(container=container)
    return container, app


def _run_trial(threads: int) -> tuple[int, int]:
    """Execute a single trial. Returns ``(winners, rejections)``.

    Winners = threads that got HTTP 201. Rejections = threads that got HTTP 409.
    Any other status (500, 4xx other) is a harness/infrastructure failure and
    raises — we refuse to silently treat it as a rejection.
    """
    _, app = _seed_single_seat_flight()
    barrier = threading.Barrier(threads)

    def _attempt(session_idx: int) -> int:
        # Per-thread TestClient avoids the ASGI test client's single-request
        # serialisation inside a single ``with`` block. Each thread owns its
        # client; they all share the same underlying ``app`` (and therefore
        # the same ``Container`` / ``SeatLockStore``), which is exactly what
        # we want the race to contest.
        with TestClient(app) as client:
            barrier.wait()
            response = client.post(
                "/seat-locks",
                json={
                    "flightId": _FLIGHT_ID,
                    "seatIds": [_SEAT_ID],
                    "sessionId": f"S-{session_idx:02d}",
                },
            )
        return response.status_code

    with ThreadPoolExecutor(max_workers=threads) as pool:
        codes = list(pool.map(_attempt, range(threads)))

    winners = sum(1 for c in codes if c == 201)
    rejections = sum(1 for c in codes if c == 409)
    unexpected = [c for c in codes if c not in (201, 409)]
    if unexpected:
        raise RuntimeError(
            f"harness observed unexpected HTTP codes {unexpected!r} — "
            "infrastructure failure, not a race outcome"
        )
    return winners, rejections


def run_harness(trials: int = 100, threads: int = 10) -> dict:
    """Run the race harness and return an aggregated summary.

    Summary shape::

        {
            "trials": <N>,
            "total_winners": <sum of winners across trials>,
            "total_rejected": <sum of rejections across trials>,
            "double_bookings": <count of trials where winners > 1>,
        }

    For the KPI-T2 gate the expected summary at N=100, T=10 is::

        {"trials": 100, "total_winners": 100,
         "total_rejected": 900, "double_bookings": 0}
    """
    summary = {
        "trials": trials,
        "total_winners": 0,
        "total_rejected": 0,
        "double_bookings": 0,
    }
    for _ in range(trials):
        winners, rejections = _run_trial(threads)
        summary["total_winners"] += winners
        summary["total_rejected"] += rejections
        if winners > 1:
            summary["double_bookings"] += 1
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Race-last-seat harness (KPI-T2 — zero double-bookings).",
    )
    parser.add_argument("--trials", type=int, default=100, help="number of trials (default 100)")
    parser.add_argument("--threads", type=int, default=10, help="threads per trial (default 10)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = run_harness(trials=args.trials, threads=args.threads)
    print(json.dumps(summary))
    return 0 if summary["double_bookings"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
