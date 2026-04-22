# DISCUSS Decisions — flight-booking-system

## Key Decisions
- [D1] **Feature type = Backend**. Interaction is HTTP/JSON only; no UI in scope this iteration. (source: interactive Decision 1)
- [D2] **Walking Skeleton = Yes (slice 01)**. Greenfield; stack uncertainty is highest up-front risk. (source: Decision 2, `slices/slice-01-walking-skeleton.md`)
- [D3] **UX research depth = Lightweight**. 3-hour exercise scope; happy path + 6 spec edge cases only. (source: Decision 3)
- [D4] **JTBD skipped**. Spec gives clear per-capability user stories. Seed jobs recorded in `docs/product/jobs.yaml` without four-forces analysis. (source: Decision 4)
- [D5] **Scope = 8 in-iteration slices + 6 deferred slices**. Slices 09–14 (modifications, cancellation fees, business-rule guardrails, group discount, operator actions, stress testing) are enumerated and prioritized but not briefed or storied in this iteration. (source: `story-map.md`)
- [D6] **Trust contract anchored on quote TTL + audit log**. The 30-minute quote freeze and append-only audit log are the two primitives that make "price-I-saw == price-I-paid" a structural guarantee, not a best-effort. (source: `outcome-kpis.md` KPI-T1, KPI-T3; slice 06 brief)
- [D7] **Exactly-one-winner concurrency test via 10-thread harness**. Slice 07 AC requires 100 trials with zero double-bookings — this is the concrete shape of "support concurrent users" from the spec. (source: slice 07 brief; KPI-T2)
- [D8] **Premium Economy deferred**. Spec mismatch (section 2 says 3 classes, Appendix A lists 4). DISCUSS default ships 3 classes; Premium Economy pricing table is preserved for future. DESIGN to confirm. (source: DoR item 3 in `dor-validation.md`)
- [D9] **Banker's rounding (half-even)** for price arithmetic. Recommended to DESIGN; all Appendix B examples validate against it. (source: slice 04 brief)
- [D10] **Quote and seat locks are session-bound**. Neither is portable across clients. Anti-abuse and simplifies the trust model. (source: `shared-artifacts-registry.md` gaps section; `dor-validation.md`)

## Requirements Summary

- **Primary user need**: A traveler can go from "I want to fly" to "confirmed booking reference" with a price they trust and a seat they specifically chose — end-to-end via HTTP.
- **Walking skeleton scope**: One hardcoded flight, base-fare price, hardcoded seat, `search → book → get booking` end-to-end. Everything else is additive.
- **Feature type**: Backend (REST API, JSON, in-memory persistence).
- **Iteration size**: 8 slices, each ≤1 day, each with a named learning hypothesis. Full backlog is 14 slices (6 deferred).

## Constraints Established

From spec:
- Flight search p95 <2s; booking creation p95 <5s; ≥10 concurrent bookings.
- Price quote valid for 30 minutes; seat lock valid for 10 minutes.
- All pricing decisions logged for audit.
- In-memory persistence only.
- Single aircraft layout (30×6).
- Bookings: max 9 passengers, advance window 11 months, min booking time 2h before departure.

From DISCUSS:
- Internal performance budgets tighter than spec (500ms search, 1000ms booking) to leave headroom.
- Commit never recomputes price; it honors the quoted total (or fails with 410 if expired).
- Seat lock survives payment failure (to its original TTL) to let travelers retry.
- Audit log is write-only in this iteration; no read endpoint.

## Upstream Changes (DISCOVER back-propagation)

DISCOVER was not run (no prior artifacts exist). DISCUSS bootstrapped SSOT (`docs/product/vision.md`, `jobs.yaml`, `journeys/book-a-flight.yaml`) from the spec PDF directly. No DISCOVER assumptions were contradicted because there were none.

## Handoff

| Target wave | Artifacts to read | Agent |
|---|---|---|
| **DESIGN** | All DISCUSS artifacts + `docs/product/` | `nw-solution-architect` |
| **DEVOPS** | `outcome-kpis.md` only | `nw-platform-architect` |

DESIGN and DEVOPS can proceed in parallel. DESIGN owns the structural decisions (layering, price function, lock primitive, quote store, audit log format, rounding); DEVOPS owns instrumentation to make KPIs measurable in CI.

## Open questions carried into DESIGN

1. Seat-class reconciliation (3 vs 4 classes) — DISCUSS default: 3 classes.
2. Quote ownership binding — DISCUSS default: session-bound.
3. Lock ownership binding — DISCUSS default: session-bound.
4. Layover / connecting flights — DISCUSS default: deferred.
5. Audit log read interface — DISCUSS default: write-only.
6. Rounding rule — DISCUSS recommendation: banker's half-even.
7. Seat classification source of truth (exit row / bulkhead location) — DISCUSS recommendation: per-seat declaration in cabin fixture.
