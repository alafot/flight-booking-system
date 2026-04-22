# DESIGN Decisions — flight-booking-system

## Key Decisions

- [D1] **Hexagonal (Ports & Adapters) modular monolith** in Python, with 4 rings (HTTP → Application → Domain → Ports/Adapters). Matches DISCUSS shared-artifacts registry 1:1. (see: `adr-001-hexagonal-oop.md`)
- [D2] **OOP paradigm** recorded in project `CLAUDE.md`. Implementation agent: `@nw-software-crafter`. Pure functions retained only for pricing + rule engines. (see: ADR-001)
- [D3] **Python 3.12 + FastAPI + Pydantic v2** as the HTTP stack. Sync handlers on a worker thread pool; no asyncio in the domain. (see: `adr-002-python-fastapi-stack.md`)
- [D4] **Money = `decimal.Decimal` with `ROUND_HALF_EVEN`** (banker's rounding). Float forbidden in domain. Verified against all three Appendix B examples to the cent. (see: `adr-003-money-decimal-banker-rounding.md`)
- [D5] **Cabin layout = per-seat `SeatKind` enum** (`STANDARD | MIDDLE | AISLE | WINDOW | EXIT_ROW | FRONT_SECTION | BULKHEAD | LIE_FLAT_SUITE | WINDOW_SUITE | AISLE_ACCESS | PRIVATE_SUITE | FRONT_ROW`). Surcharge lookup is `(class, kind) → Money`. Default layout: rows 1–2 FIRST, 3–6 BUSINESS, 7–30 ECONOMY. (see: `adr-004-cabin-layout-per-seat-classification.md`)
- [D6] **Pricing + rules = pure functions** in `domain/pricing.py` and `domain/rules.py`. Module-level constant tables. PBT via hypothesis. Boundary policy: left-inclusive, right-exclusive. (see: `adr-005-pricing-rules-pure-functions.md`)
- [D7] **QuoteStore holds immutable Quote with 30-min TTL**; `BookingService.commit` reads `quote.total` and charges that — never recomputes. (see: `adr-006-quote-store-and-audit-log.md`)
- [D8] **Audit log is append-only** (in-memory list + JSON-lines file). Events: `QuoteCreated`, `BookingCommitted`, `PaymentFailed`, `BookingCancelled`. Write-only this iteration. KPI-T3 replay via `tests/support/audit_replay.py`. (see: ADR-006)
- [D9] **Concurrency model**: sync FastAPI + `threading.RLock`. `SeatLockStore` uses store-level RLock for acquire. `BookingService.commit` holds a module-level `commit_lock` for the entire commit sequence. Proved correct for KPI-T2 via `scripts/race_last_seat.py` (100 trials × 10 threads × 0 double-bookings). (see: `adr-008-inmemory-persistence-and-lock-primitive.md`)
- [D10] **Session-bound quote + lock** via `X-Session-Id` header. Commit rejects (403) if `quote.session_id` or `lock.session_id` doesn't match the caller's session. (see: `adr-007-scope-deferments.md`)
- [D11] **Scope deferments accepted** as DESIGN decisions (not "TBD"): 3 cabin classes only (Premium Economy deferred); direct flights only (no layovers); no operator endpoints; no audit read endpoint. (see: ADR-007)

## Architecture Summary

- **Pattern**: Hexagonal / Ports & Adapters, modular monolith, single process.
- **Paradigm**: OOP (Python) with a pure functional core for pricing + rule engines.
- **Key components**:
  - `adapters/http/` — FastAPI routes, Pydantic schemas, middleware
  - `application/{search,quote,seat_hold,seat_map,booking}_service.py` — use cases
  - `domain/{model/, pricing.py, rules.py, ports.py}` — business core + ports
  - `adapters/inmemory/` — thread-safe repositories, QuoteStore, SeatLockStore
  - `adapters/mocks/` — payment, email, audit log, clock, id generator
  - `composition/wire.py` — composition root (instantiates adapters + services)

## Reuse Analysis

| Existing Component | File | Overlap | Decision | Justification |
|---|---|---|---|---|
| *(none — greenfield)* | *(n/a)* | *(n/a)* | *(n/a)* | Zero existing source in the repo; no CREATE NEW justification needed. Library-level reuse (FastAPI, Pydantic, Decimal, threading, hypothesis, uuid, logging) documented in `brief.md` — all standard-purpose reuse. |

## Technology Stack

- **Python 3.12** — current stable, pattern matching, stronger typing.
- **FastAPI 0.115+ + Pydantic v2** — HTTP + validation + OpenAPI.
- **`decimal.Decimal`** (stdlib) — money arithmetic, banker's rounding.
- **`threading`** (stdlib) — RLock for in-memory concurrency safety.
- **`hypothesis`** — property-based testing for pricing engine.
- **`pytest` + `httpx`** — unit, integration, acceptance, e2e.
- **`locust`** — KPI-P1/P2/P3 latency/throughput tests.
- **`structlog`** or stdlib `logging` with JSON formatter — KPI-O1 structured error logs.

## Constraints Established

From ADRs:
- Domain imports zero I/O modules (enforced by pre-commit grep).
- `float` is forbidden in `domain/`; use `Decimal` throughout.
- No `datetime.now()` in `pricing.py` or `rules.py`; clock must be injected.
- FastAPI's DI container is NOT used for service wiring — composition root only, to keep tests off the DI path.
- JSON-lines audit log is written synchronously inside the commit critical section.

From DISCUSS (already recorded, reaffirmed here):
- Search p95 <500ms internal (2s spec); booking commit p95 <1000ms internal (5s spec).
- Quote TTL 30 min; seat lock TTL 10 min; independent clocks.
- Payment failure does not release the lock.

## Upstream Changes (DISCUSS back-propagation)

None. All DISCUSS open questions (7 items) were resolved in the ADRs above; none contradicted or invalidated DISCUSS assumptions. No `upstream-changes.md` needed.

## Handoff

| Target wave | Artifacts to read | Agent |
|---|---|---|
| **DEVOPS** | `outcome-kpis.md` + this file + `brief.md` (for the tech stack) | `nw-platform-architect` |
| **DISTILL** | `user-stories.md` + `journey-book-a-flight.feature` + this file + ADRs | `nw-acceptance-designer` |
| **DELIVER** | Everything above + slice briefs | `nw-software-crafter` (per D2) |

DEVOPS and DISTILL can proceed in parallel. DEVOPS instruments KPIs (especially T1/T2/T3 replay checks and P1/P2/P3 load tests). DISTILL expands the Gherkin scenarios into a full acceptance suite tied to the architecture's testing layers.

## Success Criteria Gate Check

- [x] Business drivers and constraints gathered before architecture selection (read from DISCUSS)
- [x] Existing system analyzed (greenfield — confirmed, no source)
- [x] Integration points documented (mock payment, mock email, audit log sink)
- [x] Reuse Analysis table present (empty-with-note; library reuse documented separately)
- [x] Architecture supports all business requirements (KPIs traced to components)
- [x] Technology stack selected with rationale (ADR-002 through ADR-008)
- [x] Development paradigm selected (OOP) and written to CLAUDE.md
- [x] Component boundaries defined with dependency-inversion compliance (ADR-001)
- [x] C4 System Context + Container diagrams produced (`c4-diagrams.md` + optional Component view)
- [x] ADRs written with alternatives considered (8 ADRs, each with alt table)
- [ ] Handoff accepted by nw-platform-architect (DEVOPS wave) — pending next wave
