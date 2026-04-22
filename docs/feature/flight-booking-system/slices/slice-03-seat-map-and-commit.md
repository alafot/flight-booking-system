# Slice 03 — Seat Map + Seat-Specific Commit

## Goal (one sentence)
Give every flight a real 30×6 seat map with classes and statuses, and make `POST /bookings` commit a named seat that's actually there.

## IN scope
- Fixed aircraft layout: 30 rows × 6 seats (A–F); rows 1–2 First, rows 3–6 Business, rows 7–30 Economy (suggested split; DESIGN may override)
- `GET /flights/{flightId}/seats` returning per-seat: `seatId` (`"12C"`), `class`, `status` (`AVAILABLE`|`OCCUPIED`|`BLOCKED`)
- `POST /bookings` requires a valid seatId; rejects if seat doesn't exist, is OCCUPIED, or is BLOCKED
- Booking records the seat; seat becomes OCCUPIED after commit
- `GET /flights/{flightId}/seats` reflects current state after bookings

## OUT of scope
- Seat *surcharges* (slice 05 adds Appendix A pricing)
- Seat *locking* during the booking funnel (slice 07 — this slice lets the commit succeed even without a lock, but that's still first-writer-wins)
- Premium Economy (spec mismatch — section 2 lists only 3 classes; flagged in DESIGN)

## Learning hypothesis
**Disproves if fails**: Seat map is cheap to derive on demand from flight config + current bookings (no cache needed at this scale).
**Confirms if succeeds**: We can treat the seat map as a view, not a table.

## Acceptance criteria
1. `GET /flights/FL-XYZ/seats` returns 180 seats with correct class assignment and current status.
2. `POST /bookings` with a non-existent seatId → 400 with `"unknown seat"`.
3. `POST /bookings` with an OCCUPIED seatId → 409 with `"seat already booked"`.
4. `POST /bookings` with a BLOCKED seatId → 409 with `"seat not for sale"`.
5. After a successful booking for `"12C"`, `GET /flights/FL-XYZ/seats` shows `"12C"` as OCCUPIED.
6. End-to-end Gherkin scenario from `journey-book-a-flight.feature` covering happy-path seat selection passes.

## Dependencies
- Slice 01 (HTTP + repo structure)
- Slice 02 (multi-flight catalog so seat map isn't tied to one fixture)

## Effort estimate
3–4 hours.

## Pre-slice SPIKE
None required.

## Dogfood moment
Developer can `GET /flights/{id}/seats`, pick a specific seat by ID, book it, and see it flip to OCCUPIED in a subsequent GET.
