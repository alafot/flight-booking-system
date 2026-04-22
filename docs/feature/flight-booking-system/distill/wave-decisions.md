# DISTILL Decisions — flight-booking-system

## Key Decisions

- [DWD-01] **Feature file layout**: `tests/acceptance/flight-booking-system/` with `walking-skeleton.feature` + 7 `milestone-NN-*.feature` files (one per slice 02–08). Scenarios tagged `@pending` except the walking skeleton's two scenarios. (source: interactive decision)
- [DWD-02] **Walking skeleton strategy = A (Full InMemory) + tmp_path for `JsonlAuditLog`**. The walking-skeleton feature contains one `@walking_skeleton @real-io @driving_adapter` scenario exercising real HTTP through `TestClient` plus a second `@real-io @adapter-integration` scenario for `JsonlAuditLog` against a real temporary file. (source: resource-classification analysis vs DESIGN adapters)
- [DWD-03] **One-at-a-time enablement via `@pending` tag**. `pytest_collection_modifyitems` in `steps/conftest.py` auto-skips `@pending` scenarios; DELIVER removes the tag on one scenario at a time to drive the TDD cycle for each slice.
- [DWD-04] **Driving adapter = FastAPI `TestClient`**. Every WS and milestone scenario exercises an HTTP endpoint through the real app factory — no direct service invocation in `@when` steps (RCA F-005 prevention).
- [DWD-05] **Mandate 7 scaffolds applied**: every `src/flights/**/*.py` module imported by step defs exists with `__SCAFFOLD__ = True` and method bodies raising `AssertionError` (not `NotImplementedError`, not `ImportError`). This keeps the initial test run RED rather than BROKEN.
- [DWD-06] **Clock is always injected**: acceptance tests use `FrozenClock` bound to `2026-04-25 10:00:00 UTC` by default; `Scenario: ... @given("the clock is frozen at ...")` mutates the same fixture. Reinforces ADR-005's "no `datetime.now()` in domain" rule by making it testable.
- [DWD-07] **Audit coverage per Mandate 6**: every driven adapter has at least one `@real-io` scenario. In-memory stores are exercised by the WS scenario (which counts as real I/O since the InMemory adapter IS the implementation). `JsonlAuditLog` is exercised by the `@adapter-integration` scenario in `walking-skeleton.feature`.
- [DWD-08] **Graceful degradation for missing DEVOPS**: DEVOPS artifacts absent at DISTILL time. Default environment matrix applied: single `clean` environment (spec uses in-memory persistence, no pre-install/upgrade concerns). This is not a gap to DEVOPS — it's correct for the feature's scope.

## Reconciliation Result

**Reconciliation passed — 0 contradictions.** All DISCUSS D1–D10 and DESIGN D1–D11 decisions are consistent with the acceptance scenarios written here. No `upstream-issues.md` needed.

## Adapter Coverage Table (Mandate 6)

| Driven adapter | `@real-io` scenario | Covered by |
|---|---|---|
| `InMemoryFlightRepository` | YES | WS happy path (via real HTTP) |
| `InMemoryBookingRepository` | YES | WS happy path |
| `InMemoryQuoteStore` | YES | WS + milestone-06-quote-ttl-audit |
| `InMemorySeatLockStore` | YES | milestone-07-seat-locking (race harness + auto-expiry) |
| `MockPaymentGateway` | YES | WS (success path) + milestone-07 (failure path) |
| `MockEmailSender` | YES | WS (email queued assertion) |
| `JsonlAuditLog` | YES | WS adapter-integration scenario (tmp_path real file) |
| `InMemoryAuditLog` | YES | WS + milestone-06 (audit assertions) |
| `SystemClock` / `FrozenClock` | YES | Every scenario |
| `UuidIdGenerator` / `DeterministicIdGenerator` | YES | WS + all milestones |

Zero `NO — MISSING` rows. Gate satisfied.

## Driving Adapter Verification (RCA P1 fix)

DESIGN enumerated six HTTP endpoints. Each has at least one WS or milestone scenario exercising it via real HTTP:

| HTTP endpoint | Scenario exercising it via TestClient |
|---|---|
| `GET /flights/search` | WS happy path · milestone-02-catalog-search (all) · milestone-08-round-trip-filters (all) |
| `GET /flights/{id}/seats` | milestone-03-seat-map (all) |
| `POST /quotes` | milestone-04-dynamic-pricing (all) · milestone-05-price-breakdown (all) · milestone-06 |
| `POST /seat-locks` | milestone-07-seat-locking (all) |
| `POST /bookings` | WS happy path · milestone-06 · milestone-07 |
| `GET /bookings/{reference}` | WS happy path |

Zero uncovered entry points. Gate satisfied.

## Self-Review Checklist (Mandate 7 + Dimension 9)

- [x] 1. WS strategy declared in this file (DWD-02)
- [x] 2. WS scenarios tagged correctly (`@walking_skeleton @real-io` + `@real-io @adapter-integration`)
- [x] 3. Every driven adapter has at least one `@real-io` scenario (coverage table above)
- [x] 4. InMemory doubles' limitations documented: they cannot model (a) cross-process locking, (b) durable persistence, (c) real network latency — but none are in scope.
- [x] 5. Container preference: no containers (pure in-process). Documented.
- [x] 6. All production modules imported by tests have scaffold files (26 files under `src/flights/`).
- [x] 7. All scaffolds include `__SCAFFOLD__ = True` marker (grepable).
- [x] 8. All scaffold methods raise `AssertionError` (not `NotImplementedError`).
- [x] 9. Tests will be RED (not BROKEN) on first run — `AssertionError` propagates as a test failure.
- [x] 10. Driving adapter: every HTTP endpoint has at least one WS/milestone scenario via real HTTP.
- [x] 11. At least one `@real-io @adapter-integration` scenario per driven adapter (JsonlAuditLog explicit; in-memory implicit).
- [x] 12. `capsys` not used in this feature (no stdout capture needed — HTTP responses are the assertion surface).
- [x] 13. `@when` steps import ONLY from `flights.adapters.http` (TestClient) — never from `flights.adapters.inmemory.*` directly.
- [x] 14. No timing assertions <200ms in `.feature` files (the p95 500ms budget in milestone-02 is well above the 200ms floor).
- [x] 15. `sys.path` manipulation not used — package installed via `pyproject.toml`.

## Expected Outputs (produced)

```
tests/acceptance/flight-booking-system/
  __init__.py
  walking-skeleton.feature
  milestone-02-catalog-search.feature
  milestone-03-seat-map.feature
  milestone-04-dynamic-pricing.feature
  milestone-05-price-breakdown.feature
  milestone-06-quote-ttl-audit.feature
  milestone-07-seat-locking.feature
  milestone-08-round-trip-filters.feature
  steps/
    __init__.py
    conftest.py
    booking_steps.py

src/flights/                                 (Mandate 7 scaffolds)
  __init__.py
  domain/
    __init__.py
    model/
      __init__.py
      money.py, ids.py, seat.py, flight.py, passenger.py, quote.py, booking.py
    pricing.py, rules.py, ports.py
  application/
    __init__.py
    search_service.py, quote_service.py, seat_hold_service.py,
    seat_map_service.py, booking_service.py
  adapters/
    __init__.py
    http/
      __init__.py, app.py
    inmemory/
      __init__.py, flight_repository.py, booking_repository.py,
      quote_store.py, seat_lock_store.py
    mocks/
      __init__.py, payment.py, email.py, audit.py, clock.py, ids.py
  composition/
    __init__.py, wire.py

docs/feature/flight-booking-system/distill/
  walking-skeleton.md
  wave-decisions.md
```

## Handoff

| Target wave | Artifacts to read | Agent |
|---|---|---|
| **DEVOPS** | `outcome-kpis.md` + this file + `walking-skeleton.md` | `nw-platform-architect` |
| **DELIVER** | All DISTILL artifacts + slice briefs + ADRs | `@nw-software-crafter` (per DESIGN D2) |

DELIVER enters slice 01 by removing `@pending` or adding `@walking_skeleton`-targeted implementation, running the WS scenario, watching it turn from RED → GREEN, and only then moving to slice 02 (milestone-02-catalog-search.feature).

## Back-Propagation (upstream changes)

None. All DISTILL scenarios align with DISCUSS acceptance criteria and DESIGN ADRs; no upstream document required modification. No `upstream-issues.md` created.
