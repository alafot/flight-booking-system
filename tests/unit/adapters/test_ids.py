"""DeterministicIdGenerator — unit tests.

UuidIdGenerator is out of scope for step 01-02 (production-path, wired in 01-03+).
"""

from __future__ import annotations

from typing import Callable

import pytest

from flights.adapters.mocks.ids import DeterministicIdGenerator
from flights.domain.model.ids import BookingReference, QuoteId, SessionId


class TestDeterministicIdGeneratorSequences:
    @pytest.mark.parametrize(
        "kwarg,method_name,expected_first,expected_second",
        [
            (
                "booking_refs",
                "new_booking_reference",
                BookingReference("REF001"),
                BookingReference("REF002"),
            ),
            ("quote_ids", "new_quote_id", QuoteId("Q001"), QuoteId("Q002")),
            ("lock_ids", "new_lock_id", "L001", "L002"),
            (
                "session_ids",
                "new_session_id",
                SessionId("S001"),
                SessionId("S002"),
            ),
        ],
    )
    def test_emits_seeded_values_in_order(
        self,
        kwarg: str,
        method_name: str,
        expected_first: object,
        expected_second: object,
    ) -> None:
        gen = DeterministicIdGenerator(**{kwarg: (
            expected_first.value if hasattr(expected_first, "value") else expected_first,
            expected_second.value if hasattr(expected_second, "value") else expected_second,
        )})
        method: Callable[[], object] = getattr(gen, method_name)

        assert method() == expected_first
        assert method() == expected_second

    def test_exhausted_sequence_raises_index_error(self) -> None:
        gen = DeterministicIdGenerator(booking_refs=("REF001",))
        gen.new_booking_reference()

        with pytest.raises(IndexError):
            gen.new_booking_reference()
