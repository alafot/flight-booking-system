"""Audit log adapters — InMemory (mirror) and Jsonl (file) (partial scaffold).

ADR-006: append-only, synchronous write inside the commit critical section.
Step 01-02 implements ``InMemoryAuditLog.write``. ``JsonlAuditLog`` remains a
RED scaffold until step 01-03 (adapter-integration scenario).
"""

from __future__ import annotations

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
        raise AssertionError("Not yet implemented — RED scaffold (JsonlAuditLog.write)")

    def read_all(self) -> list[dict]:
        """Read back events from the file; used by auditors and replay tests."""
        raise AssertionError("Not yet implemented — RED scaffold (JsonlAuditLog.read_all)")
