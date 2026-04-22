# ADR-008 — In-memory persistence + seat-lock primitive

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

Spec allows in-memory persistence. Slice 07 requires exactly-one-winner under 10 concurrent attempts on the same seat (KPI-T2: 0 double-bookings per 100 trials). FastAPI runs sync handlers on a worker thread pool. Single-process only this iteration.

## Decision

### Persistence shape
- Every repository is a thin class wrapping a `dict` (`FlightRepository`, `BookingRepository`, `QuoteStore`, `SeatLockStore`).
- Each repository owns a `threading.RLock` for its own state — except the **shared critical section** described next.

### Shared critical section for booking commit
The sequence `read quote → read lock → charge payment → mark seat OCCUPIED on flight → save booking → release lock → write audit` **must be atomic w.r.t. other bookings on the same seats**. Achieved by:

- A module-level `threading.RLock` (`commit_lock`) held around the entire commit sequence inside `BookingService.commit`.
- This lock is coarse — one lock for the whole booking transaction space. It's acceptable because:
  - The spec's concurrency target is "10 simultaneous bookings" — trivial contention.
  - `QuoteStore.save` and `SeatLockStore.acquire` are microsecond operations; no I/O inside the lock except the local audit append and (sync) mock payment.
- Finer-grained per-flight or per-seat locks are a future optimization when the lock shows up in profiling — not before.

### Seat-lock acquisition primitive
- `SeatLockStore.acquire(seat_ids, ttl, session_id, now) → Result[SeatLock, Conflict]`.
- Under the store's own RLock:
  1. For each `seat_id`: check if an existing lock exists and is not expired.
  2. If **any** seat is locked by another session → return `Conflict(seat_ids=[...])`; install nothing.
  3. Otherwise: install a new `LockRecord` for each seat atomically, return a `SeatLock` handle.
- TTL enforcement: `acquire` treats expired lock records as free; a background sweeper is NOT needed for correctness — it's an optional memory hygiene concern.

### Concurrency proof
- **Property 1** (mutual exclusion): two acquires cannot both succeed on the same seat because step 2 above runs under the store's RLock.
- **Property 2** (no deadlock): the acquire does not hold any other lock; the commit holds `commit_lock` then calls into stores; stores never call back into services — no cycle.
- **Property 3** (liveness): RLock grants fairly; pathological starvation is not part of the spec's scope.
- Slice 07 ships `scripts/race_last_seat.py` as the empirical proof (100 trials, zero double-bookings).

## Alternatives considered

| Alt | Why rejected |
|---|---|
| asyncio with `asyncio.Lock` | FastAPI sync handlers are simpler; no benefit for a single-process in-memory system. |
| Per-seat lock stripe | Premature optimization; coarse lock is provably correct and fast enough at 10 concurrent bookings. |
| Optimistic CAS (no lock) | Requires seat status to be a single atomic field; hard to coordinate with the lock store and audit log in one step. |
| Third-party lock library | stdlib is sufficient; dependency not justified. |

## Consequences

- **+** Concurrency proof fits in one page and runs as an automated test.
- **+** The `SeatLockStore` port can later be replaced with a Redis-backed implementation for multi-process deployments — zero domain change.
- **−** The coarse `commit_lock` limits booking throughput to one-at-a-time at steady state. Acceptable: even at 10ms per commit, that's 100/s — well beyond the spec's requirement.
- **−** The in-memory `AuditLog` append must be fast (it's inside the critical section); we use an in-memory list mirror and flush to JSON-lines file after the critical section on a best-effort basis.

## Related

ADR-001 (ports), ADR-006 (audit log + quote store), slice-07 brief (concurrency harness AC).
