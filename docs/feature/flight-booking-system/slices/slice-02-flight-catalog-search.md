# Slice 02 — Flight Catalog + Search

## Goal (one sentence)
Replace the single hardcoded flight with a realistic in-memory catalog and make `GET /flights/search` a real query with pagination.

## IN scope
- Seed catalog: ≥200 flights across ≥20 routes, ≥5 airlines, ≥30 dates, ≥3 classes
- `GET /flights/search` with query params: `origin`, `destination`, `departureDate`, `passengers`, `class`
- Pagination: `page`, `size` (default 20, max 20 per spec)
- Response includes duration, stops (=0 for direct, spec shows layover support implied), and an indicative price (base × 1.0 for this slice — real pricing is slice 04)
- Input validation: valid IATA codes (3 letters), ISO date, passengers 1–9, class enum

## OUT of scope
- Round-trip (slice 08)
- Airline / price-range / time-window filters (slice 08)
- Layover computation for connections (defer — spec allows direct only on first pass)
- Dynamic pricing (slice 04)

## Learning hypothesis
**Disproves if fails**: A naïve in-memory linear scan is fast enough to meet the <2s spec with realistic catalog size.
**Confirms if succeeds**: We can defer indexing to later iterations without performance regressions.

## Acceptance criteria
1. With 200+ seeded flights, `GET /flights/search?origin=LAX&destination=NYC&departureDate=2026-06-01` returns only flights matching all three params, paginated, in <500ms p95 on dev hardware (budget headroom against 2s spec).
2. Page `1` returns the first ≤20 flights; `page=2` returns the next; `size` cannot exceed 20.
3. Invalid input → 400 with field-level error (e.g., `{"errors":[{"field":"origin","message":"must be 3-letter IATA code"}]}`).
4. Empty result → 200 with empty array and pagination metadata.
5. A performance test with the seed catalog asserts the p95 search time and fails if it regresses.

## Dependencies
- Slice 01 (HTTP layer + service + repo structure exists)

## Effort estimate
3–5 hours. Catalog seed design is the main variability.

## Pre-slice SPIKE
Optional: a 15-min SPIKE to confirm a naïve linear-scan search over 1000 flights lands well under 500ms. If it doesn't, introduce a simple origin→flights index in this slice.

## Dogfood moment
Developer can search a realistic catalog, paginate it, and see fixtures shaped like the real domain.
