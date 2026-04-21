"""ID generators.

Step 01-02 implements ``DeterministicIdGenerator`` for acceptance tests.
``UuidIdGenerator`` remains a RED scaffold — it's wired in production-path only
and will be finished when production container is needed.
"""

from __future__ import annotations

from flights.domain.model.ids import BookingReference, QuoteId, SessionId

class UuidIdGenerator:
    def new_booking_reference(self) -> BookingReference:
        raise AssertionError("Not yet implemented — RED scaffold (UuidIdGenerator.new_booking_reference)")

    def new_quote_id(self) -> QuoteId:
        raise AssertionError("Not yet implemented — RED scaffold (UuidIdGenerator.new_quote_id)")

    def new_lock_id(self) -> str:
        raise AssertionError("Not yet implemented — RED scaffold (UuidIdGenerator.new_lock_id)")

    def new_session_id(self) -> SessionId:
        raise AssertionError("Not yet implemented — RED scaffold (UuidIdGenerator.new_session_id)")


class DeterministicIdGenerator:
    """Used in acceptance tests: emits predictable ids in sequence.

    Each sequence is an independent queue. ``new_*`` pops the head and returns
    it; running out of seeded values raises ``IndexError`` (standard list
    behaviour) which tests observe as a signal that the seed was undersized.
    """

    def __init__(
        self,
        *,
        booking_refs: tuple[str, ...] = ("REF001", "REF002", "REF003"),
        quote_ids: tuple[str, ...] = ("Q001", "Q002", "Q003"),
        lock_ids: tuple[str, ...] = ("L001", "L002", "L003"),
        session_ids: tuple[str, ...] = ("S001", "S002", "S003"),
    ) -> None:
        self._booking_refs = list(booking_refs)
        self._quote_ids = list(quote_ids)
        self._lock_ids = list(lock_ids)
        self._session_ids = list(session_ids)

    def new_booking_reference(self) -> BookingReference:
        return BookingReference(self._booking_refs.pop(0))

    def new_quote_id(self) -> QuoteId:
        return QuoteId(self._quote_ids.pop(0))

    def new_lock_id(self) -> str:
        return self._lock_ids.pop(0)

    def new_session_id(self) -> SessionId:
        return SessionId(self._session_ids.pop(0))
