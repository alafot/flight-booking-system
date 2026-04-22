# ADR-002 — Python 3.12 + FastAPI + Pydantic v2

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

Need a Python HTTP framework with strong validation, automatic OpenAPI, and sync execution model that plays well with thread-based concurrency.

## Decision

- **Python 3.12** — current stable, good typing, pattern matching.
- **FastAPI 0.115+** — HTTP framework; routes run in sync mode on a worker thread pool (no asyncio in domain/services).
- **Pydantic v2** — request/response schemas; per-field 400 errors for free.

## Alternatives considered

| Alt | Why rejected |
|---|---|
| Flask + marshmallow | No built-in OpenAPI; validation less ergonomic than Pydantic. |
| Starlette (bare) | Under-specified; we'd rebuild Pydantic+router ourselves. |
| Django + DRF | Heavyweight; persistence coupling we don't want with in-memory scope. |
| FastAPI async | Spec's concurrency story is "10 simultaneous bookings" — sync + threads is sufficient and the concurrency proof is simpler. Revisit if we ever need to fan out I/O. |

## Consequences

- **+** Ships OpenAPI at `/docs` for free — useful for human verification of endpoint contracts.
- **+** Pydantic v2 uses `Decimal` cleanly, essential for money handling (ADR-003).
- **+** Sync handlers mean `threading.Lock` primitives in the seat-lock store just work (ADR-008).
- **−** FastAPI's dependency-injection system is optional but tempting — we will NOT use it for service wiring (composition root pattern instead), to keep tests from hitting FastAPI's DI container.

## Related

ADR-003 (Decimal money), ADR-008 (threading-based locks).
