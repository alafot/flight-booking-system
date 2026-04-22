# Book a Flight — Visual Journey (SSOT)

Primary actor: **Traveler** (retail customer, 1–9 passengers)
Jobs served: `job.find-flight`, `job.pick-seat`, `job.know-the-price`, `job.commit-booking`

## Narrative arc

```
  SEARCH ─────▶ INSPECT SEATS ─────▶ QUOTE PRICE ─────▶ HOLD SEATS ─────▶ COMMIT ─────▶ MANAGE
   curious       engaged             cautious           committed         relieved       (varies)
   conf:low      conf:med             conf:med          conf:med+         conf:high      conf:high
   "what         "which seat          "is this           "10-min            "it's mine    "can I change
    flies?"      do I want?"         really the         clock—hurry"       — got the     this without
                                      price?"                                reference"    surprises?"
```

## Emotional arc

Confidence **must rise monotonically** through the first five steps. The spec's dynamic pricing (Appendix B) and seat-specific surcharges (Appendix A) are the biggest threats to the arc: if the number the traveler sees at commit differs from the number they saw at search, confidence collapses and they abandon.

Design consequence: **the quote step exists specifically to freeze the number for 30 minutes**. Anything that makes the commit price diverge from the quote price is a bug in trust, not just a number.

## Shared artifacts (per `shared-artifacts-registry.md`)

| Artifact | Produced at | Consumed at | Single source of truth |
|---|---|---|---|
| `${flightId}` | search | inspect-seats, quote-price | Flight repository |
| `${selectedSeats}` | inspect-seats (client-chosen) | quote-price, hold-seats | Client → validated server-side against seat map |
| `${quoteId}` | quote-price | commit | Price quote store (expires 30 min) |
| `${priceBreakdown}` | quote-price | (display only) | Audit log |
| `${seatLock}` | hold-seats | commit | Seat lock store (expires 10 min) |
| `${bookingReference}` | commit | manage | Booking repository |

## Error paths worth naming up front

- **Double booking**: two sessions racing for the same last seat → only one wins; the other gets 409. (Spec edge case #1.)
- **Price drift**: demand changes between quote and commit → quote is honored if still within its 30-min TTL. After TTL, traveler must re-quote. (Spec edge case #2.)
- **Flight cancellation**: operator cancels a flight that has confirmed bookings → bookings move to CANCELLED, refund is owed per cancellation rules, traveler notified. (Spec edge case #3.)
- **Seat unavailable mid-flow**: seat that was AVAILABLE at inspect-seats gets taken before hold-seats → 409 with suggested alternatives. (Spec edge case #6.)

## Anti-patterns to avoid (design principles baked into the journey)

1. **Never recompute price at commit**. If the traveler saw price P, the commit charges P (until quote TTL expires). Anything else is price bait-and-switch.
2. **Seat locks must expire autonomously**, not on client action. Clients disappear; the system must not leak seats.
3. **Audit log is an output, not an afterthought.** Every price that gets charged must be explainable post-hoc.
