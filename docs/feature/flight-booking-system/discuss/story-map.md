# Story Map — flight-booking-system

## Backbone (user activities, in journey order)

```
DISCOVER FLIGHTS ──▶ INSPECT SEATS ──▶ QUOTE PRICE ──▶ HOLD SEATS ──▶ COMMIT ──▶ MANAGE
```

## Walking Skeleton (slice 01)

The thinnest end-to-end slice that ships real value:

> **Search a flight → quote a base price → commit a booking for a named seat, through the public HTTP API.**

What's intentionally *NOT* in the walking skeleton:
- No dynamic pricing (single multiplier = 1.0)
- No seat surcharges (flat base fare)
- No seat locking (first-commit-wins is OK because slice 01 is serial by contract)
- No round-trips, no filters, no pagination
- No modifications or cancellations
- No real audit log (stdout log is fine)

Why it's still a walking skeleton: it exercises **every layer of the stack** — HTTP adapter → request validation → domain service → repository → JSON response. Subsequent slices add behavioral depth without adding structural layers.

## Elephant Carpaccio slices (this iteration)

Each slice ships end-to-end in ≤1 day, has a named learning hypothesis, uses realistic fixtures, and produces visible user-level output (not just "tests green").

| # | Slice | One-line goal | Learning hypothesis (disproves if fails) | Brief |
|---|---|---|---|---|
| 01 | Walking skeleton | One hardcoded flight, base price, hardcoded seat, end-to-end commit | "Our port-adapter split survives Python/Flask wiring" | [slice-01](../slices/slice-01-walking-skeleton.md) |
| 02 | Flight catalog + search | Multiple flights, origin/destination/date search, pagination | "Search stays <2s at realistic catalog size with naive repository" | [slice-02](../slices/slice-02-flight-catalog-search.md) |
| 03 | Seat map + seat-specific commit | Seats tied to flight, classes, status; booking commits a specific seat | "Seat map is derivable from flight + bookings without caching" | [slice-03](../slices/slice-03-seat-map-and-commit.md) |
| 04 | Dynamic pricing engine (Appendix B) | Demand × time × day multipliers for any quote | "Pure pricing function matches all 3 spec examples and is PBT-testable" | [slice-04](../slices/slice-04-dynamic-pricing-engine.md) |
| 05 | Seat surcharges + taxes + fees (Appendix A) | Full price breakdown in one response | "Price breakdown contract is extensible without retrofitting the pricing formula" | [slice-05](../slices/slice-05-surcharges-taxes-fees.md) |
| 06 | Quote TTL + audit log | Quotes persist 30 min; commit honors quote price; every price is logged | "Price-I-saw == price-I-paid is provable from the audit log" | [slice-06](../slices/slice-06-quote-ttl-and-audit.md) |
| 07 | Seat locking + concurrent-booking safety | 10-min lock, race-safe under ≥10 concurrent attempts | "In-memory lock primitive yields exactly-one-winner under spec concurrency" | [slice-07](../slices/slice-07-seat-locking-concurrency.md) |
| 08 | Round-trip + filters | `returnDate`, airline/price-range/departure-time filters, class filter | "Round-trip is composable from two one-way searches without double-counting" | [slice-08](../slices/slice-08-round-trip-and-filters.md) |

## Future slices (identified, not briefed this iteration)

These are sequenced but deferred to later DISCUSS iterations. They must be briefed before execution.

| # | Slice | Why deferred |
|---|---|---|
| 09 | Booking modification (seat change up to 24h pre-departure) | Lower uncertainty; depends on 01–07 being stable |
| 10 | Cancellation fee windows (10/50/100%) | Straightforward rule table once booking state machine exists |
| 11 | Business-rule guardrails (advance booking / min booking time / capacity ceiling / passenger limit / age / documents) | Additive guards; each small individually, batch them |
| 12 | Group discount + promo codes + display-currency conversion | Pricing extensions, layered on slice 05 |
| 13 | Operator actions: seat blocking, flight cancellation refund flow | Second user class (operator); significant new contract |
| 14 | Concurrency stress test + observability polish | Validates 07 under real load; production-readiness slice |

## Slice taste-test results (gate)

| Test | Result |
|---|---|
| Any slice lists 4+ new components? | Slice 01 introduces HTTP+domain+repo+schema, which is the minimum viable greenfield stack. Acceptable because these are the stack, not 4 additions to an existing stack. |
| Every slice depends on a new abstraction shipped first? | No. Pricing function is stubbed in 01 and hardened in 04. Lock primitive is introduced in 07 (no prior slice requires it to be race-safe). |
| Any slice disproves no pre-commitment? | No. Every slice has a named hypothesis. ✓ |
| Any slice uses only synthetic data? | Realistic fixtures (Appendix B example scenarios match exact values) are mandatory per each slice AC. |
| 2+ slices identical except for scale? | 02 (catalog scale) and 14 (concurrent bookings scale) are different axes. Kept separate. ✓ |

## Scope tag rules

- No slice in this iteration is `@infrastructure`-only. Every slice produces observable user-level output.
- Slice 01 is the only one that would arguably count as infra-heavy, but it ships a real end-to-end booking reference as user-visible output → not infrastructure.
