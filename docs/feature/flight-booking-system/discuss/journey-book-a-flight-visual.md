# Journey — Book a Flight (feature: flight-booking-system)

See SSOT: [`docs/product/journeys/book-a-flight-visual.md`](../../../product/journeys/book-a-flight-visual.md)

This feature-scoped view inherits the SSOT journey and adds the acceptance lens: what must be true to accept this feature as shippable.

## Acceptance lens (what this feature must prove)

| Journey step | What must be true for acceptance |
|---|---|
| **SEARCH** | Every `GET /flights/search` with valid input returns < 2s; round-trip returns paired outbound+return. Pagination is stable and explicit. Filters compose correctly. |
| **INSPECT SEATS** | Seat map reflects current truth — includes seats held by other active locks (shown as "occupied" for that requester). Seat surcharges (Appendix A) are computed per seat and returned in the seat map. |
| **QUOTE PRICE** | Price = `base × demand × time × day × seatSurcharges + taxes + fees − discounts`. Formula result deterministic for a given `(flight, seats, passengers, now)`. Quote persists 30 min. Audit record written at quote time. |
| **HOLD SEATS** | Locks are atomic across concurrent callers: of N concurrent requests for the same seat, exactly one gets the lock; the rest get 409. Locks auto-release at TTL. |
| **COMMIT** | Transactional: either booking created + seats booked + payment charged + audit written, or *none* of the above. Quote TTL and lock TTL checked before committing. On payment failure, locks survive to the original TTL. |
| **MANAGE** | Modifications/cancellations respect the rule windows exactly. Refund math is explainable from a logged record. |

## Changes from SSOT assumptions

None on this first pass. The SSOT journey was bootstrapped from this spec; this feature IS the SSOT's initial realization.

## Emotional arc — risks unique to this feature

The spec's 3-hour target pushes against the emotional arc in two places:
1. **Quote → commit boundary**: the 30-minute quote TTL is the entire trust contract. Cut corners here and the whole journey fails.
2. **Seat lock expiry semantics**: if clients can't refresh a lock or see remaining TTL, the "committed" step feels hostile, not reassuring.

Both are flagged as DESIGN-level decisions below.
