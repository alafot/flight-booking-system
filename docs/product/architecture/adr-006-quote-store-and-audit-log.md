# ADR-006 — Quote store (30-min TTL) + Audit log (append-only)

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

The quote TTL and audit log together **are** the trust contract:
- KPI-T1 — price-I-saw == price-I-paid.
- KPI-T3 — every commit is reconstructible from the log.

They are separate concerns (quote = live state; audit = history) but must agree.

## Decision

### `QuoteStore` (port)
- Interface: `save(quote) → None`, `get(quote_id) → Optional[Quote]`, with TTL enforced **at read time** (`get` returns `None` for expired quotes, keeping the clock out of callers' mental models).
- In-memory adapter: `Dict[QuoteId, Quote]` protected by the shared seat-lock store lock — not a separate lock, because quote access is always under the same critical section as seat operations during commit (ADR-008).
- A `Quote` is immutable once saved: `{quote_id, session_id, flight_id, seat_ids, price_breakdown, expires_at, created_at}`.

### `AuditLog` (port)
- Interface: `write(event: AuditEvent) → None`. Append-only. Idempotent by event_id.
- Event types this iteration:
  - `QuoteCreated { quote_id, session_id, inputs, price_breakdown, total, created_at }`
  - `BookingCommitted { booking_reference, quote_id, total_charged, committed_at }`
  - `PaymentFailed { quote_id, reason, attempted_at }`
  - `BookingCancelled { booking_reference, refund_amount, fee_percent, cancelled_at }` (future slice 10)
- In-memory adapter: `List[AuditEvent]` + background append to a JSON-lines file at a configurable path (default `./audit.jsonl`). Writes are synchronous within the commit transaction.
- **Read is not implemented** this iteration (DISCUSS default). An auditor reads the file directly.

### KPI-T3 replay check
A test utility `tests/support/audit_replay.py` reads the audit log, replays `pricing.price(**event.inputs)` for each `QuoteCreated`, and asserts equality to `event.total`. Runs in CI after e2e tests.

## Alternatives considered

| Alt | Why rejected |
|---|---|
| Quote stored in a signed JWT (no server state) | Client can hold the JWT across sessions; breaks session-bound ownership (ADR-007). |
| Audit log in structured logger only (`logger.info(...)`) | Too easy to lose a field; replay requires a strict schema, not a log line. |
| SQL for audit | Out of scope per spec ("in-memory persistence"). Port design allows the swap later. |

## Consequences

- **+** KPI-T1 is guaranteed by design: `BookingService` reads `quote.total` and charges it — no price recomputation path exists.
- **+** KPI-T3 is guaranteed by an automated replay check; any drift is a CI failure.
- **−** JSON-lines file grows without bound in-process. Acceptable for the spec's "in-memory" scope. A rotation adapter is trivial to add later.
- **−** Quote expiry relies on a monotonic clock; the `Clock` port must be the only time source — enforced in code review.

## Related

ADR-001 (ports), ADR-003 (Decimal serialization in JSON-lines — store as string), ADR-008 (shared lock covers quote + seat mutations).
