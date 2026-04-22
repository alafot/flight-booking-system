# Architecture Brief (SSOT) — flight-booking-system

**Feature-id of origin**: `flight-booking-system` · **Wave**: DESIGN · **Architect**: nw-solution-architect
**Prior artifacts**: `docs/product/vision.md`, `docs/product/journeys/book-a-flight.yaml`, `docs/feature/flight-booking-system/discuss/*`
**ADRs**: see `docs/product/architecture/adr-*.md` in this directory

---

## Application Architecture

### Pattern: Hexagonal (Ports & Adapters) — modular monolith

Single process, single deployable. Four concentric rings:

```
  ┌─────────────────────────── HTTP Adapter (driver) ────────────────────────────┐
  │  FastAPI routers + Pydantic request/response schemas                         │
  │  Responsible for: protocol, validation, status codes, no business logic      │
  └───────────────────────────────────┬──────────────────────────────────────────┘
                                      │  calls application services
  ┌───────────────────────────────────▼──────────────────────────────────────────┐
  │                        Application Services (Use Cases)                      │
  │  SearchService · QuoteService · SeatHoldService · BookingService · SeatMapService │
  │  Responsible for: orchestration, transactions, enforcing port contracts     │
  └───────────────────────────────────┬──────────────────────────────────────────┘
                                      │  depends on domain + ports
  ┌───────────────────────────────────▼──────────────────────────────────────────┐
  │                                 Domain                                       │
  │  Aggregates/Entities: Flight, Cabin, Seat, Booking, Quote                   │
  │  Value Objects: Money, FlightId, SeatId, BookingReference, PassengerDetails │
  │  Pure functions: `price.compute(...)`, `rules.validate_booking(...)`        │
  │  Domain Events: QuoteCreated, SeatLocked, BookingConfirmed, BookingCancelled│
  │  Responsible for: the business, with zero I/O                                │
  └───────────────────────────────────┬──────────────────────────────────────────┘
                                      │  declares ports (interfaces)
  ┌───────────────────────────────────▼──────────────────────────────────────────┐
  │                           Driven Ports (interfaces)                          │
  │  FlightRepository · BookingRepository · QuoteStore · SeatLockStore          │
  │  AuditLog · PaymentGateway · EmailSender · Clock · IdGenerator              │
  └───────────────────────────────────┬──────────────────────────────────────────┘
                                      │  implemented by adapters
  ┌───────────────────────────────────▼──────────────────────────────────────────┐
  │                         Driven Adapters (this iteration)                     │
  │  InMemory* (dict + RLock) · MockPaymentGateway · MockEmailSender            │
  │  SystemClock · UuidIdGenerator · JsonlAuditLog                               │
  └──────────────────────────────────────────────────────────────────────────────┘
```

### Paradigm: Object-Oriented (Python)

Per interactive decision. OOP for services, entities, adapters. Two exceptions kept as **pure functions** in `domain/pricing.py` and `domain/rules.py`:
- **Pricing engine** is a pure function on value objects — enables property-based testing (slice 04 AC2) and makes audit-log replay (KPI-T3) trivial.
- **Rule engine** (cancellation windows, advance-booking limits, capacity ceiling) is a pure function taking a clock and a booking snapshot — one rule table, tested with boundary inputs.

Recorded in project `CLAUDE.md`: `This project follows the **object-oriented** paradigm. Use @nw-software-crafter for implementation.`

### Component boundaries (dependency inversion)

Outer rings depend on inner rings. **Domain has zero imports from infrastructure**. Adapters implement port interfaces declared by the domain/application layers.

| Component | Responsibility | Depends on |
|---|---|---|
| **http** | Route definitions, request/response schemas, middleware (error handler, request-ID) | application, domain (for response shapes) |
| **application/search_service.py** | Filter + paginate flights | FlightRepository, Clock |
| **application/quote_service.py** | Validate selected seats, compute price, persist quote, write audit entry | FlightRepository, SeatLockStore (read-only), QuoteStore, AuditLog, Clock, IdGenerator |
| **application/seat_hold_service.py** | Acquire/release seat locks atomically | SeatLockStore, FlightRepository, Clock |
| **application/seat_map_service.py** | Compose cabin + bookings + locks into a seat map view | FlightRepository, BookingRepository, SeatLockStore |
| **application/booking_service.py** | Commit a quote + lock → booking, mock payment, queue mock email, write audit | QuoteStore, SeatLockStore, BookingRepository, PaymentGateway, EmailSender, AuditLog, Clock, IdGenerator |
| **domain/pricing.py** | Pure function: `price(base, occupancy, days_before, dow, surcharges, taxes, fees) → PriceBreakdown` | (no imports from outside domain) |
| **domain/rules.py** | Pure functions: `can_book(flight, now)`, `cancellation_fee_percent(now, departure)`, etc. | (no imports from outside domain) |
| **domain/model/** | Flight, Cabin, Seat, Booking, Quote, BookingReference, Money, PassengerDetails | stdlib only |
| **adapters/inmemory/** | Thread-safe repositories + stores | threading.RLock, domain |
| **adapters/mocks/** | MockPaymentGateway, MockEmailSender | domain |

### Concurrency model

**Single-process, multi-threaded.** FastAPI runs sync endpoints on a worker thread pool; no asyncio in the domain or services. This simplifies the concurrency proof:

- **Seat-lock primitive (ADR-006)**: the `InMemorySeatLockStore` uses a single module-level `threading.RLock` protecting the lock table (`Dict[SeatId, LockRecord]`). `acquire(seat_ids, ttl, session_id) → Result[SeatLock]` performs a check-then-mutate under the lock: if all seats are free (no valid lock entry for each seat_id, or the existing lock has expired per clock), it installs a new lock atomically and returns it; otherwise returns a conflict listing the occupied seat ids. Tested by slice 07's concurrency harness (100 trials × 10 threads × 0 double-bookings).
- **Booking commit**: the BookingService verifies `quote.valid(now) ∧ lock.valid(now) ∧ lock.session_id == quote.session_id` before any state mutation. All mutations (lock release, seat → OCCUPIED on flight, booking create, audit write) happen under the same module-level lock; any adapter-level lock is inside this critical section.
- **No distributed locking.** Single process. If we ever go multi-process, the port contract is already in place — we replace `InMemorySeatLockStore` with a Redis-backed adapter, no domain change.

### Trust contract (how the journey's emotional arc is defended)

The DISCUSS emotional arc depends on **quote fidelity** (price-I-saw = price-I-paid) and **exactly-once seat booking**. The architecture enforces these structurally, not by discipline:

1. `QuoteService` writes an immutable `Quote` record containing the full `PriceBreakdown` and a 30-min `expires_at`. The record is keyed by `quote_id` and cannot be mutated.
2. `BookingService.commit(quote_id, lock_id, passenger_details, payment_token)` reads the stored `Quote.total` and charges that value — it never recomputes price. If the stored quote is expired → 410 Gone.
3. `AuditLog` is append-only; it persists one record at quote time (full pricing inputs + computed total) and one at commit time (quote_id + booking_reference). KPI-T3's replay check reads these two records and asserts equality.
4. Seat-lock TTL and quote TTL are independent clocks. Payment failure does not release the lock — the lock lives on its own TTL so the traveler can retry. This is enforced by BookingService's error handling (payment exception → no state change beyond an audit-log entry for the failed attempt).

### Scope decisions resolved here (from DISCUSS open questions)

| Question | DESIGN decision | ADR |
|---|---|---|
| Seat classes | 3 classes: Economy, Business, First. Premium Economy surcharge table preserved in code but unreachable until cabin config changes. | ADR-007 |
| Quote ownership | Session-bound. Client supplies `X-Session-Id` header (opaque token); quote's `session_id` must match on commit. | ADR-007 |
| Lock ownership | Same — session-bound via the same `X-Session-Id`. | ADR-007 |
| Layovers | Direct flights only; `stops=0` always. Layover modeling deferred. | ADR-007 |
| Audit log reads | Write-only (append to JSON-lines file or in-memory list). No read endpoint this iteration. | ADR-006 |
| Rounding | `decimal.ROUND_HALF_EVEN` (banker's). Verified against all three Appendix B examples to the cent. | ADR-003 |
| Seat classification (exit row, bulkhead, etc.) | **Per-seat** declaration in the cabin fixture (`Seat.kind: EXIT_ROW \| FRONT_SECTION \| AISLE \| WINDOW \| MIDDLE \| STANDARD`). Pricing looks up surcharge by `(class, kind)`. | ADR-004 |

### Technology stack

| Concern | Choice | Notes |
|---|---|---|
| Language | **Python 3.12** | Matches ADR-002. Pattern matching, `typing.Self`, better error messages. |
| HTTP framework | **FastAPI 0.115+** | Pydantic-native, OpenAPI for free, supports sync handlers. |
| Validation | **Pydantic v2** | Per-field 400 errors out of the box. |
| Money | **`decimal.Decimal`** with context set to `ROUND_HALF_EVEN`, 2-dp quantization | Single `Money` value object; `float` is forbidden in domain. |
| IDs | `uuid.uuid4()` for internal ids; booking references are 6-char base32 derived from uuid | Readable + uniqueness |
| Persistence | In-memory (dict-backed) with `threading.RLock` | Port contract allows swap to SQL later |
| Audit log | Append-only JSON-lines file (configurable path) + in-memory mirror for tests | Port: `AuditLog.write(event)` |
| Payment | `MockPaymentGateway` | Port: `PaymentGateway.charge(token, amount) → PaymentResult` |
| Email | `MockEmailSender` that records queued emails | Port: `EmailSender.queue_confirmation(booking)` |
| Clock | `SystemClock` + `FrozenClock` for tests | Port: `Clock.now() → datetime` |
| Testing | **pytest** + **hypothesis** (PBT) + **httpx** (e2e against the live app) | hypothesis drives KPI-C1 worked-examples + pricing property tests |
| Observability | `structlog` or stdlib `logging` with JSON formatter | Request-id middleware; all non-2xx responses emit a structured log (KPI-O1) |
| Load / concurrency testing | `locust` for KPI-P1/P2/P3; a dedicated `race_last_seat.py` harness using stdlib `threading` for KPI-T2 | |
| Packaging | `pyproject.toml` with `hatchling`; `uv` or `pip` for installs | |

### Layered source tree (target)

```
flight-booking-system/
├── pyproject.toml
├── src/
│   └── flights/
│       ├── domain/
│       │   ├── model/            # Flight, Cabin, Seat, Booking, Quote, Money, ...
│       │   ├── pricing.py        # pure function + multiplier tables
│       │   ├── rules.py          # pure functions for business rules
│       │   └── ports.py          # Protocol classes for driven ports
│       ├── application/
│       │   ├── search_service.py
│       │   ├── quote_service.py
│       │   ├── seat_hold_service.py
│       │   ├── seat_map_service.py
│       │   └── booking_service.py
│       ├── adapters/
│       │   ├── http/              # FastAPI app, routers, schemas, middleware
│       │   ├── inmemory/          # InMemoryFlightRepository, etc.
│       │   └── mocks/             # MockPaymentGateway, MockEmailSender, JsonlAuditLog
│       └── composition/
│           └── wire.py            # Composition root: instantiates adapters & services
├── tests/
│   ├── unit/                      # pure fn tests (pricing, rules)
│   ├── integration/               # services against in-memory adapters
│   ├── acceptance/                # Gherkin scenarios from DISCUSS
│   └── e2e/                       # race_last_seat.py + locust
└── scripts/
    └── race_last_seat.py          # KPI-T2 concurrency harness
```

---

## Reuse Analysis

Greenfield project — no pre-existing components in this repo. The table below is intentionally empty per the mandatory gate; a brief note follows on library choices (which are legitimate forms of reuse analysis).

| Existing Component | File | Overlap | Decision | Justification |
|---|---|---|---|---|
| *(none)* | *(greenfield)* | *(n/a)* | *(n/a)* | No prior source. All components in the target tree are new. |

**Library reuse (analysis-worthy 'existing components' available as dependencies)**:

| Library | Why we reuse (vs writing) | Where |
|---|---|---|
| `fastapi` + `pydantic v2` | HTTP framework + validation — writing these is a cost with no learning hypothesis. | `adapters/http/` |
| `decimal` (stdlib) | Money arithmetic — rolling our own decimal would be a defect factory. | `domain/model/money.py`, `domain/pricing.py` |
| `threading` (stdlib) | RLock primitive is enough for single-process concurrency (ADR-005). | `adapters/inmemory/seat_lock_store.py` |
| `hypothesis` | PBT for slice 04 pricing AC2 — writing a PBT harness is out of scope. | `tests/unit/test_pricing.py` |
| `uuid` (stdlib) | Id generation. | `adapters/mocks/uuid_id_generator.py` |
| `logging` (stdlib) + JSON formatter | Structured logs for KPI-O1. | HTTP middleware + `adapters/mocks/jsonl_audit_log.py` |

No library introduces CREATE NEW: every library above is a well-known component used for its standard purpose.
