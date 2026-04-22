# Outcome KPIs — flight-booking-system

Measurable outcomes the system must meet. Every KPI has a numeric target and a measurement method.

## Trust KPIs (core to the emotional arc)

### KPI-T1 — Quote fidelity
- **Metric**: Percentage of commits within quote TTL where charged total == quoted total.
- **Target**: 100.0% (any deviation is a P0 bug).
- **Measurement**: Derived from the audit log — every commit entry compared to its parent quote entry. CI job runs this check after every e2e test run.

### KPI-T2 — Exactly-once seat booking under concurrency
- **Metric**: In any window where N concurrent requests target the same seat, exactly one succeeds; the others return 409.
- **Target**: 0 double-bookings per 100 trials of a 10-thread race harness (per slice 07 AC).
- **Measurement**: `scripts/race_last_seat.py` runs 100 trials in CI; fail if any trial has winners != 1.

### KPI-T3 — Audit coverage
- **Metric**: Percentage of commits for which the pricing inputs + total can be reconstructed from the audit log.
- **Target**: 100.0%.
- **Measurement**: Replay check — for each booking in the system, a CI job re-derives the price from the logged inputs and asserts equality to the charged total.

## Performance KPIs (from spec)

### KPI-P1 — Flight search latency
- **Metric**: p95 response time of `GET /flights/search` under the seeded catalog.
- **Target**: <2000ms (spec); internal budget <500ms (headroom).
- **Measurement**: k6 or locust load test against the HTTP endpoint with 200+ flight catalog; records p50/p95/p99.

### KPI-P2 — Booking creation latency
- **Metric**: p95 response time of `POST /bookings` under realistic quote + lock state.
- **Target**: <5000ms (spec); internal budget <1000ms.
- **Measurement**: Same harness as KPI-P1.

### KPI-P3 — Concurrent booking throughput
- **Metric**: System sustains ≥10 concurrent booking attempts without errors or deadlocks.
- **Target**: 10 concurrent successful bookings across different seats complete within KPI-P2 target.
- **Measurement**: Concurrency harness (10 threads, different seats) runs in CI.

## Correctness KPIs (from spec business rules)

### KPI-C1 — Pricing accuracy
- **Metric**: Every one of Appendix B's three worked examples produces the documented total to the cent.
- **Target**: 3/3.
- **Measurement**: Unit tests assert the exact cent values; run in CI.

### KPI-C2 — Edge case coverage
- **Metric**: All six spec "Edge Cases" covered by passing Gherkin scenarios.
- **Target**: 6/6.
- **Measurement**: `journey-book-a-flight.feature` scenarios execute against the running system; all green in CI.

### KPI-C3 — Business rule enforcement
- **Metric**: Advance booking (11 months), min booking time (2h), passenger limit (9), capacity ceiling (95%), cancellation fee windows (10/50/100%) each blocked or applied correctly when triggered.
- **Target**: 5/5 rules enforced; 0/5 bypassable.
- **Measurement**: Dedicated rule tests; all green in CI.

## Operational KPIs

### KPI-O1 — Error logging
- **Metric**: Every non-2xx response produces a structured log entry with request ID, endpoint, status code, and reason.
- **Target**: 100.0% coverage.
- **Measurement**: Middleware emits log; CI test asserts log presence for a set of failing-request fixtures.

## KPI ownership

KPIs are owned by the platform-architect (nw-platform-architect, DEVOPS wave) for observability instrumentation and the solution-architect (nw-solution-architect, DESIGN wave) for correctness design. This DISCUSS artifact hands off to both.
