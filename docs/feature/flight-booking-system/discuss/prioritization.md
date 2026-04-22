# Prioritization — flight-booking-system

Slice execution order with rationale per slice.

| Order | Slice | Primary driver | Why at this position |
|---|---|---|---|
| 1 | 01 walking skeleton | Learning leverage | Highest structural uncertainty — proves the Python HTTP/domain/repo stack works before we invest in business logic. Failure here means restart; we want to find out cheaply. |
| 2 | 04 dynamic pricing engine | Learning leverage | Highest *business-logic* uncertainty. The spec gives three worked examples (Appendix B) — if our formula doesn't match, the whole pricing contract is wrong. Find out next. |
| 3 | 07 seat locking + concurrency | Learning leverage | Highest *concurrency* uncertainty. Spec calls out double-booking as an edge case; without a lock primitive that actually works, edge case #1 is broken. Resolve the hardest unknown early. |
| 4 | 02 flight catalog + search | Performance uncertainty | Spec requires <2s search. Catalog size and filter shape are naïvely a linear scan — cheaper to check early than after we've built more on top. |
| 5 | 03 seat map + seat-specific commit | Dependency chain | 05, 06, 09, 10 all need a booking that carries specific seats. Unblocks the rest of the backlog. |
| 6 | 05 surcharges + taxes + fees | Dependency chain | Required before 06 can claim "price-I-saw == price-I-paid" is meaningful — "price" without surcharges is fiction. |
| 7 | 06 quote TTL + audit | Dependency chain + trust contract | This is the trust-contract slice (the one the journey's emotional arc depends on). Come after pricing is whole so the quote we freeze is the real quote. |
| 8 | 08 round-trip + filters | Learning leverage (low) | Mostly additive; low risk. Ships real user-facing scope expansion, good slice to end the "core" iteration on. |

## Re-prioritization triggers

Move a slice **earlier** if:
- It blocks a stakeholder-committed demo
- A dependency is discovered to be riskier than estimated

Move a slice **later** if:
- Its hypothesis has already been confirmed by an earlier slice (don't repeat learning)
- Its acceptance criteria can be satisfied by a cheaper alternative

## Dogfood moments

Each slice ends with a callable HTTP endpoint that a developer can hit from curl/httpie and see the behavior land. No slice hides value behind internal APIs only.

## Release bucketing (not slicing)

If forced to cut, cut the tail: 08, then 06 (fold audit-log AC into 05), then 05 (support base + tax only). Never cut 01–04 or 07 — they are the core trust contract.
