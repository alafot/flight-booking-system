"""E2E tests for the race-last-seat harness (KPI-T2).

The harness is the single source of truth for the "zero double-bookings" gate.
These tests exercise ``scripts.race_last_seat.run_harness`` in-process so the
same code path that an engineer would invoke via ``python scripts/race_last_seat.py``
is what CI measures.

Two tests:

* ``test_harness_returns_perfect_run_for_10_trials`` — fast smoke (~1-2s) run
  on every push to catch regressions in the harness wiring itself.
* ``test_harness_returns_perfect_run_for_100_trials`` — the KPI-T2 gate
  (100 trials × 10 threads = 1,000 lock attempts) required by milestone-07.
"""

from __future__ import annotations

from scripts.race_last_seat import run_harness


def test_harness_returns_perfect_run_for_10_trials() -> None:
    """A 10-trial smoke run must show 10 winners, 90 rejections, 0 double-bookings.

    One winner per trial × 10 trials = 10 winners. Nine rejections per trial
    × 10 trials = 90 rejections. ZERO trials may have more than one winner
    (any >1 is a double-booking, which fails KPI-T2).
    """
    summary = run_harness(trials=10, threads=10)

    assert summary == {
        "trials": 10,
        "total_winners": 10,
        "total_rejected": 90,
        "double_bookings": 0,
    }, f"smoke run did not produce a perfect summary: {summary!r}"


def test_harness_returns_perfect_run_for_100_trials() -> None:
    """KPI-T2 gate: 100 trials × 10 threads, zero double-bookings."""
    summary = run_harness(trials=100, threads=10)

    assert summary["trials"] == 100
    assert summary["total_winners"] == 100, (
        f"expected 100 winners (one per trial), got {summary['total_winners']}: "
        f"{summary!r}"
    )
    assert summary["total_rejected"] == 900, (
        f"expected 900 rejections (9 per trial), got {summary['total_rejected']}: "
        f"{summary!r}"
    )
    assert summary["double_bookings"] == 0, (
        f"KPI-T2 violation: {summary['double_bookings']} trial(s) produced "
        f"more than one winner — {summary!r}"
    )
