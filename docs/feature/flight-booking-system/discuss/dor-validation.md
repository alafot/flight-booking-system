# Definition of Ready (DoR) Validation — flight-booking-system

DISCUSS cannot hand off until all 9 DoR items are satisfied with evidence.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | **Business value is clear** | ✅ | `docs/product/vision.md` states the "deciding and committing a purchase with confidence" outcome and what success looks like. Every user story has an Elevator Pitch with a decision the user can make. |
| 2 | **User and jobs are identified** | ✅ | Primary user: The Traveler (retail, 1–9 passengers) — `docs/product/vision.md`. Seed jobs in `docs/product/jobs.yaml` (JTBD skipped per Decision 4; these are seed jobs, not validated JTBD). Every story traces to at least one seed job. |
| 3 | **Scope is explicit (IN / OUT)** | ✅ | `journey-book-a-flight.yaml` `feature_scope_notes` (in_scope / out_of_scope / contradictions_to_reconcile_in_design); `story-map.md` names 8 in-this-iteration slices and 6 deferred slices. |
| 4 | **Acceptance criteria are testable** | ✅ | Every story has concrete AC referencing HTTP endpoints and observable JSON output. The Gherkin file `journey-book-a-flight.feature` provides executable scenarios for happy path + all 6 spec edge cases. |
| 5 | **Non-functional requirements are documented** | ✅ | `outcome-kpis.md` enumerates performance (<2s search, <5s booking, ≥10 concurrent), trust (quote fidelity, exactly-once booking, audit coverage), correctness (pricing, edge cases, business rules), and operational (error logging) targets with measurement methods. |
| 6 | **Shared artifacts / data contracts are named** | ✅ | `shared-artifacts-registry.md` names every `${variable}` passed between journey steps with producer, consumers, and single source of truth. Gaps flagged for DESIGN (quote ownership, lock ownership, audit read interface). |
| 7 | **Error paths are mapped** | ✅ | Journey yaml `failure_modes` per step; Gherkin scenarios for all 6 spec edge cases; `journey-book-a-flight-visual.md` "Error paths worth naming up front". |
| 8 | **Slicing is disciplined (elephant carpaccio)** | ✅ | 8 slices, each ≤1 day, each with a named learning hypothesis, each with its own slice brief under `../slices/`. Taste-test results documented in `story-map.md`. No `@infrastructure`-only slices. |
| 9 | **Ownership and handoff are clear** | ✅ | DISCUSS owner: Luna (nw-product-owner). Next wave: DESIGN (full artifact set → nw-solution-architect), DEVOPS (outcome-kpis.md only → nw-platform-architect). Handoff specified in `wave-decisions.md`. |

## Peer review

This DISCUSS output is ready for peer review. Suggested reviewer: `nw-por-reviewer` (product owner reviewer).

### Reviewer checklist (gates for handoff approval)

- [ ] Every user story's Elevator Pitch has a real endpoint and a real observable output (not "service call succeeds").
- [ ] Every acceptance criterion is decidable without human judgement.
- [ ] Every slice brief identifies its highest-uncertainty piece (hypothesis).
- [ ] Scope contradictions between sections 2 and Appendix A of the spec (Premium Economy vs 3 classes) are flagged and carried forward to DESIGN.
- [ ] The quote-TTL / lock-TTL / audit contract is coherent — i.e., a commit that cites a valid quote and a valid lock will charge the quote price and release the lock.
- [ ] Performance KPIs have headroom against the spec's hard targets.

### Scope items that DESIGN must resolve

These were flagged during DISCUSS and cannot be resolved here:

1. **Seat-class reconciliation**: Spec section 2 lists 3 classes (Economy/Business/First); Appendix A lists 4 (adds Premium Economy). DISCUSS default: ship 3 classes; preserve Premium Economy surcharges as future.
2. **Quote ownership semantics**: Is a quote portable across clients or bound to the requesting session? DISCUSS default: session-bound.
3. **Lock ownership semantics**: Same question for seat locks. DISCUSS default: session-bound.
4. **Layover / connecting flights**: Spec mentions layovers but doesn't specify. DISCUSS default: direct flights only in scope; layovers deferred.
5. **Audit log read interface**: No read endpoint specified. DISCUSS default: write-only audit log for this iteration.
6. **Rounding rule** for pricing arithmetic: banker's half-even recommended; DESIGN to confirm.
