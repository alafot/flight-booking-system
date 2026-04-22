# Slice 06 — Quote TTL + Audit Log

## Goal (one sentence)
Make quotes persist for 30 minutes, commit the quoted price (not a fresh recompute), and write every pricing decision to an audit log.

## IN scope
- `POST /quotes` creating a `${quoteId}` with a 30-minute `expiresAt`
- `POST /bookings` accepts a `quoteId`; charges the quoted `total` (not a recomputed one) if the quote is still valid
- Quote store (in-memory)
- Append-only audit log: one entry per quote creation and per commit; entries include `quoteId`, `bookingReference` (on commit), inputs used for pricing, and the computed total
- Quote expiry: commit with expired quote → 410 Gone

## OUT of scope
- External/persistent audit log storage (in-memory is fine)
- Operator-side audit read endpoint (out of scope; auditors can read the log file for now)
- Partial commit / partial refund audit (slice 10)

## Learning hypothesis
**Disproves if fails**: We can prove "price I saw == price I paid" from the audit log alone — no other state needed.
**Confirms if succeeds**: Trust contract with the traveler is structurally guaranteed.

## Acceptance criteria
1. `POST /quotes` returns `quoteId`, `total`, `expiresAt` 30 min in the future; audit log gets an entry.
2. `POST /bookings` with a valid, unexpired quote charges exactly the quoted `total`, regardless of any changes to demand/time/day inputs since the quote was issued.
3. `POST /bookings` with an expired quote → 410 Gone with message "quote expired, please re-quote".
4. `POST /bookings` with an unknown quoteId → 404.
5. Audit log contains one entry per quote and one per commit, each with a timestamp and full input snapshot (occupancy, days-before, departure day, seat surcharges, taxes, fees).
6. Given any booking reference, an auditor can reconstruct the committed price from the audit log entries.

## Dependencies
- Slice 05 (price breakdown is stable)

## Effort estimate
3–5 hours.

## Pre-slice SPIKE
None required.

## Open question
- **Quote ownership**: should a quote be usable by any client or only the one that created it? Recommended default: bound to the requesting session identifier (anti-scraping). Flag for DESIGN.

## Dogfood moment
Developer POSTs a quote, waits, POSTs a booking citing the quoteId, and can show an auditor the log file proving the charged total matches.
