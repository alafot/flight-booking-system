"""InMemoryQuoteStore — unit tests.

Port-to-port at driven-port scope: ``save`` and ``get_valid`` only. The store
enforces TTL at read time — callers pass ``now`` and expired quotes return
``None`` (comparison uses ``>=`` so the exact ``expires_at`` instant is
expired, matching the 30-minute-exclusive-upper-bound contract in ADR-006).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flights.adapters.inmemory.quote_store import InMemoryQuoteStore
from flights.domain.model.ids import FlightId, QuoteId, SeatId, SessionId
from flights.domain.model.money import Money
from flights.domain.model.quote import PriceBreakdown, Quote


_CREATED_AT = datetime(2026, 4, 25, 10, 0, tzinfo=UTC)
_EXPIRES_AT = _CREATED_AT + timedelta(minutes=30)


def _make_quote(quote_id: str = "Q001") -> Quote:
    """Build a minimal well-formed Quote for store round-tripping.

    The pricing fields are narrative defaults — the store does not inspect
    them, so identity and TTL are what the assertions track.
    """
    return Quote(
        id=QuoteId(quote_id),
        session_id=SessionId("S-001"),
        flight_id=FlightId("FL-LAX-NYC-0800"),
        seat_ids=(SeatId("12C"),),
        passengers=1,
        price_breakdown=PriceBreakdown(
            base_fare=Money.of("299"),
            demand_multiplier=Decimal("1.00"),
            time_multiplier=Decimal("1.00"),
            day_multiplier=Decimal("1.00"),
        ),
        created_at=_CREATED_AT,
        expires_at=_EXPIRES_AT,
    )


class TestInMemoryQuoteStoreGetValid:
    def test_save_then_get_valid_round_trips_quote(self) -> None:
        store = InMemoryQuoteStore()
        quote = _make_quote()

        store.save(quote)

        # ``now`` strictly before expiry → store returns the saved instance.
        retrieved = store.get_valid(QuoteId("Q001"), _CREATED_AT)
        assert retrieved is quote

    def test_get_valid_returns_none_for_unknown_quote_id(self) -> None:
        """Before any save (or for an id that was never saved), get_valid
        must return None — the store never fabricates quotes."""
        store = InMemoryQuoteStore()
        assert store.get_valid(QuoteId("Q-MISSING"), _CREATED_AT) is None

    def test_get_valid_returns_none_after_expires_at(self) -> None:
        """One minute past ``expires_at``, the quote is expired."""
        store = InMemoryQuoteStore()
        quote = _make_quote()
        store.save(quote)

        expired_now = _EXPIRES_AT + timedelta(minutes=1)

        assert store.get_valid(QuoteId("Q001"), expired_now) is None

    def test_get_valid_at_exact_expires_at_instant_returns_none(self) -> None:
        """``now == expires_at`` counts as expired — the TTL window is
        [created_at, expires_at) (half-open), per ADR-006. A caller arriving
        at the boundary reads None, not the quote."""
        store = InMemoryQuoteStore()
        quote = _make_quote()
        store.save(quote)

        assert store.get_valid(QuoteId("Q001"), _EXPIRES_AT) is None

    def test_get_valid_one_microsecond_before_expires_at_returns_quote(
        self,
    ) -> None:
        """The last valid instant is exactly one datetime-tick before
        ``expires_at``. Pairs with the ``==`` boundary test above to pin the
        half-open window in both directions."""
        store = InMemoryQuoteStore()
        quote = _make_quote()
        store.save(quote)

        just_before = _EXPIRES_AT - timedelta(microseconds=1)

        assert store.get_valid(QuoteId("Q001"), just_before) is quote
