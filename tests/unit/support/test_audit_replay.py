"""Unit tests for the ``tests.support.audit_replay`` helper.

Driving port: the two public module-level functions ``replay_quote`` and
``verify_commits``. Pure functions → calling them directly IS port-to-port
testing (the function signature is the public interface).

Behavior budget: 4 distinct behaviors × 2 = 8 max. Four tests implemented —
each probing one observable outcome:

  1. ``replay_quote`` reproduces Appendix B example 1 exactly.
  2. ``verify_commits`` returns an empty list when every BookingCommitted
     reconciles with its matching QuoteCreated.
  3. ``verify_commits`` reports a ReplayMismatch when the replayed total
     disagrees with the charged amount.
  4. ``verify_commits`` skips the ``Q000-WS`` sentinel (the walking-skeleton
     marker meaning "no upstream quote was created"), so bookings charged at
     base fare never produce spurious mismatches.
"""

from __future__ import annotations

from typing import Any


def test_replay_quote_reproduces_appendix_b_example_1_total() -> None:
    """Appendix B example 1: 299 USD base, 0% occupancy, 30 days out, Tuesday.

    Multiplier path: demand=1.00 (bucket [0,31)), time=0.90 (bucket 21..59),
    day=0.85 (TUE). Raw = 299 × 1.00 × 0.90 × 0.85 = 228.735 → rounded per
    the Appendix B rule (banker-round at cents, 3 is odd → round up) →
    228.74. The event shape mirrors what ``QuoteService._build_audit_event``
    writes.
    """
    from tests.support.audit_replay import replay_quote

    event = {
        "type": "QuoteCreated",
        "quote_id": "Q-TEST-001",
        "session_id": "S-TEST",
        "flight_id": "FL-TEST",
        "seat_ids": ["12C"],
        "occupancy_pct": "0",
        "days_before_departure": 30,
        "departure_dow": "TUE",
        "base_fare": "299",
        "total": "228.74",
        "created_at": "2026-04-25T10:00:00+00:00",
        "expires_at": "2026-04-25T10:30:00+00:00",
    }

    breakdown = replay_quote(event)

    assert str(breakdown.total.amount) == "228.74"


def test_verify_commits_returns_empty_when_replayed_total_matches_charged() -> None:
    """A BookingCommitted whose ``total_charged`` matches the replayed total
    of its QuoteCreated produces zero mismatches.

    We pin a 0% occupancy / 30-day-out / Tuesday flight so demand=1.00,
    time=0.90, day=0.85 → total = 299 × 0.90 × 0.85 = 228.74 after the
    Appendix B rounding rule (see ``replay_quote`` docs).
    """
    from tests.support.audit_replay import verify_commits

    events: list[dict[str, Any]] = [
        {
            "type": "QuoteCreated",
            "quote_id": "Q-MATCH-001",
            "session_id": "S-MATCH",
            "flight_id": "FL-TEST",
            "seat_ids": ["12C"],
            "occupancy_pct": "0",
            "days_before_departure": 30,
            "departure_dow": "TUE",
            "base_fare": "299",
            "total": "228.74",
            "created_at": "2026-04-25T10:00:00+00:00",
            "expires_at": "2026-04-25T10:30:00+00:00",
        },
        {
            "type": "BookingCommitted",
            "booking_reference": "REF001",
            "quote_id": "Q-MATCH-001",
            "flight_id": "FL-TEST",
            "seat_ids": ["12C"],
            "total_charged": "228.74",
            "at": "2026-04-25T10:05:00+00:00",
        },
    ]

    assert verify_commits(events) == []


def test_verify_commits_reports_mismatch_when_charged_total_drifts() -> None:
    """If the charged total doesn't match the replayed quote total, the
    function returns a ReplayMismatch naming the offending booking
    reference and describing the drift."""
    from tests.support.audit_replay import verify_commits

    events: list[dict[str, Any]] = [
        {
            "type": "QuoteCreated",
            "quote_id": "Q-DRIFT-001",
            "session_id": "S-DRIFT",
            "flight_id": "FL-TEST",
            "seat_ids": ["12C"],
            "occupancy_pct": "0",
            "days_before_departure": 30,
            "departure_dow": "TUE",
            "base_fare": "299",
            "total": "228.74",
            "created_at": "2026-04-25T10:00:00+00:00",
            "expires_at": "2026-04-25T10:30:00+00:00",
        },
        {
            "type": "BookingCommitted",
            "booking_reference": "REF-DRIFT",
            "quote_id": "Q-DRIFT-001",
            "flight_id": "FL-TEST",
            "seat_ids": ["12C"],
            "total_charged": "999.00",  # arbitrary drift from 254.15
            "at": "2026-04-25T10:05:00+00:00",
        },
    ]

    mismatches = verify_commits(events)

    assert len(mismatches) == 1
    mismatch = mismatches[0]
    assert mismatch.booking_reference == "REF-DRIFT"
    assert "228.74" in mismatch.reason
    assert "999.00" in mismatch.reason


def test_verify_commits_skips_ws_shortcut_quote_id() -> None:
    """``Q000-WS`` is the walking-skeleton sentinel meaning "no upstream
    quote". BookingCommitted events bearing this id must be skipped so the
    WS flow (base-fare charging, no quote read on commit) does not produce
    spurious mismatches before Phase 06-03 wires commit-reads-quote.
    """
    from tests.support.audit_replay import verify_commits

    events: list[dict[str, Any]] = [
        {
            "type": "QuoteCreated",
            "quote_id": "Q-OTHER",
            "session_id": "S-OTHER",
            "flight_id": "FL-TEST",
            "seat_ids": ["12C"],
            "occupancy_pct": "0",
            "days_before_departure": 30,
            "departure_dow": "TUE",
            "base_fare": "299",
            "total": "228.74",
            "created_at": "2026-04-25T10:00:00+00:00",
            "expires_at": "2026-04-25T10:30:00+00:00",
        },
        {
            "type": "BookingCommitted",
            "booking_reference": "REF-WS",
            "quote_id": "Q000-WS",
            "flight_id": "FL-TEST",
            "seat_ids": ["12C"],
            "total_charged": "299.00",  # base fare; does not match Q-OTHER's total
            "at": "2026-04-25T10:05:00+00:00",
        },
    ]

    assert verify_commits(events) == []
