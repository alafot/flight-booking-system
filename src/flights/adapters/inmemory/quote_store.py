"""InMemoryQuoteStore — in-process quote persistence with read-time TTL.

Per ADR-006 the store is a driven port. ``save`` is unconditional; TTL
enforcement lives at read time so the caller's clock is the authoritative
source (rather than a background expiry sweep which would introduce
non-determinism under the FrozenClock). The TTL window is half-open:
``[created_at, expires_at)`` — a caller arriving at exactly ``expires_at``
reads None, matching the 30-minute-exclusive upper bound contract.
"""

from __future__ import annotations

import threading
from datetime import datetime

from flights.domain.model.ids import QuoteId
from flights.domain.model.quote import Quote


class InMemoryQuoteStore:
    def __init__(self) -> None:
        self._quotes: dict[QuoteId, Quote] = {}
        self._lock = threading.RLock()

    def save(self, quote: Quote) -> None:
        with self._lock:
            self._quotes[quote.id] = quote

    def get_valid(self, quote_id: QuoteId, now: datetime) -> Quote | None:
        """Return the saved quote iff ``now < quote.expires_at``, else None.

        The ``>=`` comparison treats the exact ``expires_at`` instant as
        expired — the 30-minute window is half-open per ADR-006.
        """
        with self._lock:
            quote = self._quotes.get(quote_id)
            if quote is None:
                return None
            if now >= quote.expires_at:
                return None
            return quote
