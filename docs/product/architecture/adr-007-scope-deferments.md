# ADR-007 — Scope deferments (Premium Economy, layovers, session binding, audit reads)

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

DISCUSS carried seven open questions into DESIGN. This ADR records the decisions for the scope-related ones so they don't get lost or re-litigated.

## Decisions

### 1. Three cabin classes this iteration
- Implemented: `SeatClass.ECONOMY | BUSINESS | FIRST`.
- **Premium Economy** enum value and surcharge table are **preserved in code** (as commented-out or flag-gated entries in `pricing.SURCHARGES`) but unreachable from any cabin fixture.
- Rationale: spec section 2 explicitly lists 3 classes; Appendix A lists 4. We ship what matches the cabin layout. When a second cabin is introduced, flip the flag.

### 2. Quote + seat lock are session-bound
- Every quote and every seat lock records a `session_id`.
- Clients supply `X-Session-Id` as an HTTP header. If absent, the HTTP layer generates one, returns it in `Set-Cookie`, and echoes it in the response body (so API-only clients see it).
- `BookingService.commit` rejects (403) if the supplied quote or lock was created by a different `session_id`.
- Rationale: anti-abuse + simplified semantics for the trust contract.

### 3. Layovers / connecting flights deferred
- All flights are direct (`stops=0`, `layovers=[]`).
- `FlightOffer` schema still carries `stops` and `layovers` fields so the response shape is forward-compatible.
- Rationale: spec mentions layovers but doesn't detail them; not worth the complexity for this iteration.

### 4. Audit log is write-only
- No `GET /audit/...` endpoint.
- Auditors read the JSON-lines file directly, or call the in-memory mirror in tests.
- Rationale: spec is silent on an audit read surface; exposing one is a design choice, not a requirement.

### 5. Operator endpoints out of scope
- Seat BLOCKED status exists in the data model and seat map, but there is no endpoint to toggle it this iteration — BLOCKED seats only come from the cabin fixture.
- Flight cancellation by operator is likewise out of scope; the Gherkin scenario for spec edge-case #3 remains as a documented behavior, not an implemented endpoint.
- Rationale: operator is a second user class whose requirements aren't detailed in the spec; deferred to slice 13.

## Alternatives considered

Each deferment was considered against "ship it now" and rejected because of the 3-hour time budget and the lack of spec detail.

## Consequences

- **+** Clear scope boundary: DEVOPS and DELIVER know what endpoints to expect.
- **+** Every deferment has a code-level marker (flag or comment) so the future addition is obvious.
- **−** Session binding adds one header to the HTTP contract; documented in the OpenAPI spec.

## Related

ADR-004 (cabin layout supports but doesn't ship Premium Economy), ADR-006 (audit log is write-only by decision, not limitation).
