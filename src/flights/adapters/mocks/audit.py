"""Audit log adapters — InMemory (mirror) and Jsonl (file).

ADR-006: append-only, synchronous write inside the commit critical section.
Step 01-02 implemented ``InMemoryAuditLog``. Step 01-03 adds the real-I/O
``JsonlAuditLog`` which appends JSON-lines to a file on disk — the primary
persistence adapter for the audit trail.

Non-JSON-serialisable fields (``Decimal``, ``BookingReference``, etc.) are
coerced to strings via ``default=str`` so the write never fails on domain
value objects.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path


class InMemoryAuditLog:
    """In-memory mirror; primary test surface for assertions."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self._lock = threading.RLock()

    def write(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)


class JsonlAuditLog:
    """Append-only JSON-lines file. Used by adapter-integration test with tmp_path."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def write(self, event: dict) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event, default=str)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")

    def read_all(self) -> list[dict]:
        """Read back events from the file; used by auditors and replay tests."""
        with self._lock:
            if not self._path.exists():
                return []
            with self._path.open("r", encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
