"""InMemoryAuditLog — unit tests.

JsonlAuditLog is out of scope for step 01-02 (its integration test ships in 01-03).
"""

from __future__ import annotations

from flights.adapters.mocks.audit import InMemoryAuditLog


class TestInMemoryAuditLogWrite:
    def test_write_appends_single_event(self) -> None:
        log = InMemoryAuditLog()

        log.write({"type": "QuoteCreated", "quote_id": "Q001"})

        assert log.events == [{"type": "QuoteCreated", "quote_id": "Q001"}]

    def test_write_preserves_order_across_multiple_events(self) -> None:
        log = InMemoryAuditLog()

        log.write({"type": "QuoteCreated"})
        log.write({"type": "BookingCommitted"})
        log.write({"type": "PaymentFailed"})

        assert [e["type"] for e in log.events] == [
            "QuoteCreated",
            "BookingCommitted",
            "PaymentFailed",
        ]
