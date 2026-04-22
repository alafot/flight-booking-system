# Walking Skeleton — Design Notes

**SSOT**: `tests/acceptance/flight-booking-system/walking-skeleton.feature`
**Strategy**: A — Full InMemory + tmp_path for `JsonlAuditLog` (DWD-02)
**Driving adapter**: FastAPI via `httpx.TestClient`

## What the WS scenarios prove

The walking-skeleton `.feature` file contains two scenarios. Together they prove:

1. **End-to-end booking via real HTTP** (`@walking_skeleton @real-io @driving_adapter`)
   - Real HTTP (via `TestClient`) → real FastAPI routes → real application services → real domain objects → real in-memory repositories → real in-memory audit mirror → real FastAPI response.
   - Exercises every layer of the hexagonal stack. If this scenario passes, the stack is wired correctly.
   - Explicitly out of scope for the skeleton: dynamic pricing, seat surcharges, seat locking, quote TTL — all those are milestones 04/05/06/07.

2. **`JsonlAuditLog` adapter integration** (`@real-io @adapter-integration`)
   - Real filesystem via `tmp_path`. Writes three events, reads them back, asserts file shape + contents.
   - This is the ONLY driven adapter in the feature that touches the filesystem; it needs its own integration scenario because the InMemory mirror cannot prove durable write semantics.

## What the WS scenarios intentionally do NOT prove

- **Dynamic pricing correctness** — deferred to milestone-04 (Appendix B examples to the cent).
- **Concurrency correctness** — deferred to milestone-07 (ten-thread race harness, 100 trials, zero double-bookings).
- **Quote trust contract** — deferred to milestone-06 (quote honored after TTL inputs change; 410 after TTL).
- **Error paths** — the skeleton tests the happy path only; milestones cover errors (409/410/422/402).

## Execution flow (step-by-step, what happens during the WS run)

The WS scenario takes the following path (after DELIVER implements the scaffolds):

```
  TestClient.get("/flights/search?...")
    → FastAPI router → search_flights() handler
      → container.search_service.search(SearchRequest(...))
        → InMemoryFlightRepository.search(origin, dest, date, ...)
      ← list[Flight]
    ← JSON response

  TestClient.post("/bookings", json={...})
    → FastAPI router → post_booking() handler
      → container.booking_service.commit(CommitRequest(...))
        → [holds booking_service.commit_lock]
          → container.flight_repo.get(flight_id)
          → container.payment.charge(token, amount)
          → container.booking_repo.save(booking)
          → container.email.queue_confirmation(booking)
          → container.audit.write({type: "BookingCommitted", ...})
        [releases commit_lock]
      ← Booking
    ← JSON response with bookingReference + status

  TestClient.get("/bookings/{ref}")
    → FastAPI router → get_booking() handler
      → container.booking_service.get(reference)
    ← JSON response
```

## Dependencies of the WS scenario

| What the scenario needs | Source | Status today |
|---|---|---|
| `create_app(container)` | `src/flights/adapters/http/app.py` | Scaffolded (routes raise AssertionError → RED) |
| `build_test_container(now, audit_path, deterministic_ids)` | `src/flights/composition/wire.py` | Scaffolded (raises AssertionError — the fixture chain goes RED here first) |
| `FrozenClock(now).set(instant)` | `src/flights/adapters/mocks/clock.py` | **Functional** (no AssertionError — test choreography only) |
| `Flight`, `Cabin`, `Seat` with enums | `src/flights/domain/model/*.py` | **Functional** data classes (dataclass constructors work) |
| `InMemoryFlightRepository.add(flight)` | `src/flights/adapters/inmemory/flight_repository.py` | **Functional** (simple dict write) |
| `JsonlAuditLog.write` / `.read_all` | `src/flights/adapters/mocks/audit.py` | Scaffolded (raises AssertionError → RED for the adapter scenario) |

### Why some scaffolds are functional and others raise

**Mandate 7 principle**: *"raise an exception classified as assertion failure (RED), not infrastructure error (BROKEN)"*. Data classes that the test-arrange phase uses (`Flight`, `Seat`, `Money.of`) must actually work — otherwise the `@given` background step itself throws before the production code under test gets a chance. Business methods (`BookingService.commit`, `pricing.price`, `InMemorySeatLockStore.acquire`, ...) raise `AssertionError` so the test fails during the `@when` / `@then` phases, which is what the RED classification requires.

## How DELIVER enables one scenario at a time

1. DELIVER picks the next slice (01 first).
2. DELIVER removes the scaffold from the slice's code paths (e.g., implements `BookingService.commit` + `post_booking` route + `build_test_container`).
3. DELIVER runs `pytest tests/acceptance/flight-booking-system/walking-skeleton.feature -m walking_skeleton`. It was RED; it should now be GREEN.
4. DELIVER moves to slice 02 by removing `@pending` from one scenario in `milestone-02-catalog-search.feature` and repeating.
5. When all milestones are green and zero `__SCAFFOLD__ = True` markers remain in `src/flights/`, the feature is done.

## Scaffold detection

- `grep -R "__SCAFFOLD__ = True" src/flights/` — should return empty after DELIVER completes all milestones.
- `pytest -m "walking_skeleton"` — should be GREEN after slice 01.
- `pytest -m "walking_skeleton or not pending"` — progressively turns GREEN as DELIVER removes `@pending` tags.

## Limitations of the strategy

- **Single-process concurrency only**. The WS race-harness (milestone-07) runs 10 threads in one process against the in-memory SeatLockStore. It does NOT prove correctness across multiple processes or across machines. That would require a SQL or Redis adapter — explicitly out of scope per spec.
- **No real payment/email**. Both are in-process mocks. The contract (that a failed charge doesn't release the seat lock) is testable through the mock; production integration requires adapter swaps.
- **No durable persistence**. All repositories vanish on process exit. Re-running the WS from scratch always starts with an empty catalog.

These limitations are intentional (per spec: "in-memory persistence is fine") and are documented here so DELIVER and reviewers can see them without reading the whole ADR set.
