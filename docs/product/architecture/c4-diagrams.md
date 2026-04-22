# C4 Diagrams — flight-booking-system

Mermaid-rendered C4 views. Levels 1 (System Context) and 2 (Container) are mandatory per DESIGN wave. Level 3 (Component) is included for the Booking subsystem because it houses the trust contract (ADR-006 + ADR-008).

---

## Level 1 — System Context

```mermaid
C4Context
title System Context — Flight Booking System

Person(traveler, "Traveler", "A retail customer booking 1–9 seats.")
Person_Ext(operator, "Operator (deferred)", "Airline operations staff; blocks seats, cancels flights. Not an actor in this iteration.")
Person_Ext(auditor, "Auditor", "Reads the append-only audit log to verify pricing decisions.")

System(fbs, "Flight Booking System", "Hexagonal Python backend exposing a REST API for search, quote, seat-hold, booking, and booking management.")

System_Ext(payment, "Mock Payment Gateway", "Charges a traveler's payment token (mocked; no real processor).")
System_Ext(email, "Mock Email Sender", "Queues booking-confirmation emails (mocked; no delivery).")

Rel(traveler, fbs, "Search, quote, hold, book", "HTTPS/JSON")
Rel(fbs, payment, "Charge payment token", "In-process port (mock)")
Rel(fbs, email, "Queue confirmation", "In-process port (mock)")
Rel(auditor, fbs, "Reads", "audit.jsonl (file)")

UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

**Notes**
- The operator is drawn as external/deferred — no endpoint this iteration (ADR-007).
- Payment and email are *in-process* mocks accessed via ports — shown as external systems for protocol clarity (they will become real external systems in later iterations without domain change).
- Auditor is an offline actor; they read the audit log file, not an API.

---

## Level 2 — Container

```mermaid
C4Container
title Container — Flight Booking System (single process)

Person(traveler, "Traveler", "")

System_Boundary(fbs, "Flight Booking System (one process)") {
  Container(http, "HTTP API", "FastAPI + Pydantic v2, Python 3.12", "Routes, request/response validation, middleware (request-id, error envelope, structured logs)")
  Container(app, "Application Services", "Python / OOP", "SearchService, QuoteService, SeatHoldService, SeatMapService, BookingService. Owns the commit critical section.")
  Container(domain, "Domain", "Python / pure", "Flight, Seat, Booking, Quote, Money, PassengerDetails. Pure fns: pricing.py, rules.py. Declares driven ports.")
  ContainerDb(repos, "In-Memory Repositories", "Python dict + threading.RLock", "FlightRepository, BookingRepository, QuoteStore, SeatLockStore")
  Container(audit, "Audit Log", "Append-only JSON-lines (file + in-memory mirror)", "QuoteCreated, BookingCommitted, PaymentFailed, BookingCancelled")
  Container(mocks, "Mock Adapters", "Python", "MockPaymentGateway, MockEmailSender, SystemClock, UuidIdGenerator")
}

Rel(traveler, http, "HTTPS/JSON", "port 8000")
Rel(http, app, "Calls services", "Python")
Rel(app, domain, "Uses value objects + pure fns", "Python")
Rel(app, repos, "Read/write", "port interfaces")
Rel(app, audit, "Append", "AuditLog port")
Rel(app, mocks, "Charge / send / time / id", "port interfaces")
Rel(domain, repos, "Declares port", "Port interfaces only — no dependency on adapter")

UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

**Notes**
- Domain declares ports; repositories/adapters implement them. Arrow goes from `app → repos` because services call ports; domain "owns" the interfaces but doesn't call them.
- All containers run in the **same OS process** — no IPC, no network between containers. Boundaries are Python module boundaries.

---

## Level 3 — Component (Booking subsystem — the trust contract)

```mermaid
C4Component
title Component — Booking subsystem (where quote TTL + seat lock + audit converge)

Container_Boundary(app, "Application Services") {
  Component(bsvc, "BookingService.commit", "Python", "Holds commit_lock; verifies quote+lock; charges payment; creates booking; writes audit; releases lock")
  Component(qsvc, "QuoteService.quote", "Python", "Computes price via domain.pricing.price; saves quote; writes QuoteCreated audit event")
  Component(lsvc, "SeatHoldService.acquire", "Python", "Atomic CAS on SeatLockStore under store lock")
}

Container_Boundary(domain, "Domain") {
  Component(pricing, "domain.pricing.price", "Python / pure", "Deterministic: base × demand × time × day × surcharges + taxes + fees")
  Component(rules, "domain.rules.*", "Python / pure", "can_book, advance_booking_ok, capacity_ok, cancellation_fee_percent")
}

Container_Boundary(repos, "In-Memory Stores") {
  Component(qstore, "QuoteStore", "Python dict", "TTL enforced at read time")
  Component(lstore, "SeatLockStore", "Python dict + RLock", "Seat-lock acquire/release primitive (ADR-008)")
  Component(brepo, "BookingRepository", "Python dict", "Saves Booking records; idempotent by reference")
}

Component(auditlog, "AuditLog (JsonlAuditLog)", "Python", "Append-only; writes to in-memory list + JSON-lines file")
Component(pay, "MockPaymentGateway", "Python", "Returns SUCCESS / FAILED based on token; no real network")

Rel(qsvc, pricing, "compute")
Rel(qsvc, rules, "capacity_ok, can_book")
Rel(qsvc, qstore, "save")
Rel(qsvc, auditlog, "QuoteCreated")

Rel(lsvc, lstore, "acquire/release")

Rel(bsvc, qstore, "get(quote_id) — read-only in critical section")
Rel(bsvc, lstore, "validate + release under commit_lock")
Rel(bsvc, pay, "charge(token, amount)")
Rel(bsvc, brepo, "save(booking)")
Rel(bsvc, auditlog, "BookingCommitted / PaymentFailed")

UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

**Notes**
- `BookingService.commit` reads `quote.total` from `QuoteStore` — **never recomputes price**. This is the structural guarantee behind KPI-T1.
- `auditlog.append(QuoteCreated(...))` is inside the same critical section as the price computation in `QuoteService`, guaranteeing "every quote has an audit record" (KPI-T3).
- `SeatHoldService` runs outside the commit critical section; its own store lock handles concurrent acquires (ADR-008, "Property 1").

---

## Deployment view (informative)

Single container/process:

```mermaid
flowchart LR
  subgraph host[Developer machine or container]
    py[Python 3.12 process]
    py -->|stdout/stderr| logs[(Structured logs)]
    py -->|appends| jsonl[(audit.jsonl)]
  end
  client[curl / httpx / locust] -->|HTTP :8000| py
```

No external services. `audit.jsonl` path is configurable via env var (default `./audit.jsonl`).
