"""MockEmailSender.

Records queued confirmations in-memory for test inspection. Tests read
``.queued`` directly — this is the primary assertion surface.
"""

from __future__ import annotations

from flights.domain.model.booking import Booking


class MockEmailSender:
    """Records queued confirmations in-memory for test inspection."""

    def __init__(self) -> None:
        self.queued: list[Booking] = []

    def queue_confirmation(self, booking: Booking) -> None:
        self.queued.append(booking)
