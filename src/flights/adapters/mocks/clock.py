"""Clock adapters (scaffold).

SystemClock wraps datetime.now; FrozenClock is for tests — returns a configured
instant that can be advanced.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

__SCAFFOLD__ = True


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class FrozenClock:
    """Deterministic clock for acceptance and unit tests."""

    def __init__(self, instant: datetime) -> None:
        self._now = instant

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set(self, instant: datetime) -> None:
        self._now = instant
