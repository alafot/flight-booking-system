"""Audit-log replay utility.

Reconstructs a ``PriceBreakdown`` from a ``QuoteCreated`` audit event by
replaying the pure pricing function against the same inputs, and reconciles
``BookingCommitted`` events against their matching ``QuoteCreated`` parents
to prove the charged total is reproducible from the audit trail alone.

Phase 06-02 contract:

* ``replay_quote(event)`` consumes a QuoteCreated event dict and invokes
  ``pricing.price`` with the fields the event pins. Surcharges/taxes/fees
  are not present in the event shape and are passed as zero — the milestone
  scenarios constrain quotes to the subset of pricing that excludes them,
  and Phase 06-03 may extend the event schema once commit-reads-quote is
  wired.

* ``verify_commits(events)`` walks the event log looking for pairs:
  BookingCommitted events matched by ``quote_id`` to a prior QuoteCreated.
  The sentinel id ``Q000-WS`` identifies walking-skeleton commits that
  were charged at ``flight.base_fare`` without reading a quote; those are
  explicitly skipped so the invariant is trivially satisfied for the WS
  flow. Phase 06-03 will retire the sentinel once commit honors the quote.

Both functions are pure (no I/O, no clock, no randomness); the only
side-effect-free dependency is ``flights.domain.pricing`` + ``flights.domain.model``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from flights.domain import pricing
from flights.domain.model.money import Money
from flights.domain.model.quote import PriceBreakdown
from flights.domain.pricing import DayOfWeek, PricingInputs

# Sentinel quote id used by BookingService when no upstream quote existed
# (walking-skeleton path). Phase 06-03 removes this.
_WS_SHORTCUT_QUOTE_ID = "Q000-WS"


@dataclass(frozen=True)
class ReplayMismatch:
    """Reported when a BookingCommitted event's total_charged cannot be
    reproduced from its matching QuoteCreated event.

    ``reason`` is a human-readable diagnostic that names both the replayed
    and the charged totals, so failures are actionable without re-running
    the replay under a debugger.
    """

    booking_reference: str
    reason: str


def replay_quote(event: dict) -> PriceBreakdown:
    """Reconstruct the ``PriceBreakdown`` from a ``QuoteCreated`` event.

    The event shape is the one emitted by ``QuoteService._build_audit_event``
    — any field added to that event that changes the price must be reflected
    here, or the replay drifts silently (caught by ``verify_commits``).
    """
    dow = DayOfWeek[event["departure_dow"]]
    return pricing.price(
        PricingInputs(
            base_fare=Money.of(event["base_fare"]),
            occupancy_pct=Decimal(event["occupancy_pct"]),
            days_before_departure=int(event["days_before_departure"]),
            departure_dow=dow,
            # surcharges / taxes / fees are not carried in the event shape
            # this iteration; Phase 06-03 extends the schema if needed.
        )
    )


def verify_commits(events: list[dict]) -> list[ReplayMismatch]:
    """Reconcile every BookingCommitted event against its matching
    QuoteCreated. Returns an empty list on a perfect trail.

    * Commits bearing the ``Q000-WS`` sentinel are skipped (walking-skeleton
      shortcut — see module docstring).
    * A commit whose ``quote_id`` has no matching QuoteCreated is a
      mismatch ("quote not found").
    * A commit whose replayed total does not string-equal ``total_charged``
      is a mismatch with both values in the reason.
    """
    quotes_by_id = {
        event["quote_id"]: event
        for event in events
        if event.get("type") == "QuoteCreated"
    }
    mismatches: list[ReplayMismatch] = []
    for event in events:
        if event.get("type") != "BookingCommitted":
            continue
        quote_id = event.get("quote_id")
        if quote_id == _WS_SHORTCUT_QUOTE_ID:
            continue
        booking_reference = event.get("booking_reference", "<unknown>")
        matching_quote = quotes_by_id.get(quote_id)
        if matching_quote is None:
            mismatches.append(
                ReplayMismatch(
                    booking_reference=booking_reference,
                    reason=f"quote not found for quote_id={quote_id!r}",
                )
            )
            continue
        replayed = replay_quote(matching_quote)
        charged = event.get("total_charged", "<missing>")
        if str(replayed.total.amount) != charged:
            mismatches.append(
                ReplayMismatch(
                    booking_reference=booking_reference,
                    reason=(
                        f"replayed={replayed.total.amount} "
                        f"charged={charged}"
                    ),
                )
            )
    return mismatches
