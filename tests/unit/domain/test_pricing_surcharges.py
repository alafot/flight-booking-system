"""Appendix A seat-surcharge lookup — unit tests.

Port-to-port at domain scope per nw-tdd-methodology: the public
``lookup_seat_surcharge`` function and the module-level ``SURCHARGES`` table
are the driving port for this slice. No HTTP, no mocks, deterministic.

Coverage:
  * Every Appendix A (class, kind) → Money anchor lookups to the cent
    (one parametrized behavior: "known pair returns configured amount").
  * Unmapped (class, kind) pair returns ``Money.of("0")`` (the neutral
    default — a kind that isn't priced for that class has no surcharge).
  * Structural invariant: the ``SURCHARGES`` table exposes the full
    Appendix A coverage required by ADR-004 so future edits are
    single-location. (Premium Economy is deferred per ADR-007 and
    deliberately absent from ``SeatClass`` — it isn't asserted here.)

Test-budget: 2 behaviors × 2 = 4 tests (2 parametrized + 1 structural).
"""

from __future__ import annotations

import pytest

from flights.domain import pricing
from flights.domain.model.money import Money
from flights.domain.model.seat import SeatClass, SeatKind
from flights.domain.pricing import lookup_seat_surcharge

# --- Appendix A anchor list --------------------------------------------------
#
# Single source of truth for the parametrized lookup test. If the ADR-004
# table changes, this list is the only place that needs editing in the test
# suite — the assertion below iterates it. The pairs mirror the ``SURCHARGES``
# entries that step 05-01 must populate.

APPENDIX_A_ANCHORS: list[tuple[SeatClass, SeatKind, str]] = [
    # Economy (ADR-004)
    (SeatClass.ECONOMY, SeatKind.STANDARD, "0.00"),
    (SeatClass.ECONOMY, SeatKind.EXIT_ROW, "35.00"),
    (SeatClass.ECONOMY, SeatKind.FRONT_SECTION, "25.00"),
    (SeatClass.ECONOMY, SeatKind.AISLE, "15.00"),
    (SeatClass.ECONOMY, SeatKind.WINDOW, "15.00"),
    (SeatClass.ECONOMY, SeatKind.MIDDLE, "-5.00"),
    # Business (ADR-004)
    (SeatClass.BUSINESS, SeatKind.STANDARD, "0.00"),
    (SeatClass.BUSINESS, SeatKind.LIE_FLAT_SUITE, "200.00"),
    (SeatClass.BUSINESS, SeatKind.WINDOW_SUITE, "100.00"),
    (SeatClass.BUSINESS, SeatKind.AISLE_ACCESS, "75.00"),
    # First (ADR-004)
    (SeatClass.FIRST, SeatKind.STANDARD, "0.00"),
    (SeatClass.FIRST, SeatKind.PRIVATE_SUITE, "500.00"),
    (SeatClass.FIRST, SeatKind.FRONT_ROW, "150.00"),
]


class TestLookupSeatSurchargeKnownPair:
    """Behavior: ``lookup_seat_surcharge(class, kind)`` returns the exact
    Appendix A Money amount for every mapped (class, kind) pair.
    """

    @pytest.mark.parametrize(
        "seat_class,kind,expected",
        APPENDIX_A_ANCHORS,
        ids=[f"{c.value}-{k.value}" for c, k, _ in APPENDIX_A_ANCHORS],
    )
    def test_returns_configured_amount_for_every_appendix_a_pair(
        self, seat_class: SeatClass, kind: SeatKind, expected: str
    ) -> None:
        assert lookup_seat_surcharge(seat_class, kind) == Money.of(expected)


class TestLookupSeatSurchargeUnknownPair:
    """Behavior: for a (class, kind) pair absent from the table, the lookup
    returns ``Money.of("0")`` — the neutral default per the step brief.

    Parametrized over representative unmapped pairs so adding a new SeatKind
    that isn't priced for a given class doesn't silently break this contract.
    """

    @pytest.mark.parametrize(
        "seat_class,kind",
        [
            (SeatClass.ECONOMY, SeatKind.LIE_FLAT_SUITE),  # Biz kind in Econ cabin
            (SeatClass.ECONOMY, SeatKind.PRIVATE_SUITE),  # First kind in Econ cabin
            (SeatClass.BUSINESS, SeatKind.MIDDLE),  # Econ kind in Biz cabin
            (SeatClass.BUSINESS, SeatKind.EXIT_ROW),  # Econ kind in Biz cabin
            (SeatClass.FIRST, SeatKind.MIDDLE),  # Econ kind in First cabin
            (SeatClass.FIRST, SeatKind.LIE_FLAT_SUITE),  # Biz kind in First cabin
        ],
        ids=lambda p: p.value if hasattr(p, "value") else str(p),
    )
    def test_returns_zero_money_for_unmapped_pair(
        self, seat_class: SeatClass, kind: SeatKind
    ) -> None:
        assert lookup_seat_surcharge(seat_class, kind) == Money.of("0")


class TestSurchargesTableAsSingleSourceOfTruth:
    """ADR-004 + ADR-005: the ``SURCHARGES`` dict is the one authoritative
    location for seat-surcharge values. Structural invariants — not value
    invariants — so edits to the Appendix A numbers flow through
    ``TestLookupSeatSurchargeKnownPair`` without breaking this test.
    """

    def test_surcharges_table_is_module_level_and_covers_all_three_classes(
        self,
    ) -> None:
        # Attribute access at module level, not via a factory or singleton.
        assert hasattr(pricing, "SURCHARGES"), "pricing.SURCHARGES must be a module-level dict"
        classes_present = {seat_class for seat_class, _ in pricing.SURCHARGES.keys()}
        # ADR-007: Premium Economy deferred; the three enabled classes must be covered.
        assert classes_present == {SeatClass.ECONOMY, SeatClass.BUSINESS, SeatClass.FIRST}, (
            f"SURCHARGES missing classes; got {classes_present}"
        )
