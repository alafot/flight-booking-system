"""Adapter-integration tests for ``JsonlAuditLog``.

Verifies the real filesystem adapter round-trips audit events: writes
JSON-lines to disk and reads them back in order. The filesystem is real
(``tmp_path``) — this is the minimum Mandate 6 real-I/O coverage for the
audit log adapter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from flights.adapters.mocks.audit import JsonlAuditLog


def test_jsonl_audit_log_round_trips_events_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = JsonlAuditLog(path)
    events = [
        {
            "type": "QuoteCreated",
            "seq": 0,
            "at": datetime(2026, 4, 25, 10, 0, tzinfo=UTC).isoformat(),
        },
        {
            "type": "BookingCommitted",
            "seq": 1,
            "at": datetime(2026, 4, 25, 10, 1, tzinfo=UTC).isoformat(),
        },
        {
            "type": "PaymentFailed",
            "seq": 2,
            "at": datetime(2026, 4, 25, 10, 2, tzinfo=UTC).isoformat(),
        },
    ]

    for event in events:
        log.write(event)

    assert path.exists()
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 3
    parsed = [json.loads(ln) for ln in lines]
    assert [e["type"] for e in parsed] == ["QuoteCreated", "BookingCommitted", "PaymentFailed"]

    round_trip = log.read_all()
    assert round_trip == events


def test_jsonl_audit_log_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "audit.jsonl"
    log = JsonlAuditLog(path)

    log.write({"type": "QuoteCreated", "seq": 0})

    assert path.exists()
    assert log.read_all() == [{"type": "QuoteCreated", "seq": 0}]


def test_read_all_on_empty_path_returns_empty_list(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    log = JsonlAuditLog(path)

    assert log.read_all() == []
