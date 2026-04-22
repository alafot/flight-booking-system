# Slice 07 — Seat Locking + Concurrent-Booking Safety

## Goal (one sentence)
Make the "last seat on a flight" scenario race-safe: ≥10 concurrent attempts to book it, exactly one wins, the others get a clean 409.

## IN scope
- `POST /seat-locks` (or equivalent endpoint in the booking flow) that atomically acquires a 10-min lock on one or more seats for one caller
- Commit flow: `POST /bookings` checks the lock is held and unexpired before charging
- Locks auto-expire at TTL (no client release required)
- Seat map reports locked-by-others seats as unavailable
- Concurrency test simulating ≥10 simultaneous lock attempts on the same last seat

## OUT of scope
- Durable lock storage (in-memory only is fine for this exercise)
- Lock extension/refresh by the holder (defer)
- Explicit lock release endpoint (defer — TTL-based release is sufficient for spec)
- Distributed locking primitives (single-process only)

## Learning hypothesis
**Disproves if fails**: A simple in-process lock primitive (single-writer + compare-and-swap on seat status) is enough to enforce exactly-one-winner under spec concurrency.
**Confirms if succeeds**: No need for a distributed lock manager for this exercise's scope.

## Acceptance criteria
1. Concurrency test: with 10 threads attempting to lock the same seat, exactly one receives a lock, the other 9 receive HTTP 409 "seat unavailable". Total run across 100 trials: *zero* cases of two winners, *zero* cases of zero winners when the seat was available.
2. An acquired lock TTL of 10 minutes is enforced: after 10 minutes with no commit, the seat returns to AVAILABLE without any client action.
3. `GET /flights/{id}/seats` reflects locked-by-other seats as unavailable.
4. Committing with an expired lock → 410 Gone.
5. Payment failure during commit does NOT release the lock prematurely (it survives until its original TTL, so the traveler can retry).

## Dependencies
- Slice 03 (seat map exists)
- Slice 06 (quote TTL exists — the quote TTL and lock TTL are different clocks; slice must document why)

## Effort estimate
5–7 hours. The concurrency test harness is a meaningful part of the estimate.

## Pre-slice SPIKE (RECOMMENDED)
**Yes — 30 min.** Before writing the slice code, SPIKE the locking primitive (asyncio lock vs threading lock vs compare-and-swap on a dict) with a 10-thread hammer-test to confirm the chosen primitive actually holds. This is the highest-uncertainty piece.

## Open question
- **Quote vs lock clocks**: 30-min quote, 10-min lock. If lock expires, can the traveler re-acquire a lock on the same seats against the same quote? Recommended default: yes, provided the seat is still available — this keeps the quote's trust contract without leaking seats.

## Dogfood moment
Developer runs the 10-thread test script and sees "1 winner, 9 rejected, 0 double-bookings" across 100 trials.
