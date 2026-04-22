# Slice 08 — Round-Trip Search + Filters

## Goal (one sentence)
Extend `GET /flights/search` with `returnDate`, airline, price-range, and departure-time filters so travelers can actually compare real round-trip options.

## IN scope
- `returnDate` query parameter: when present, response pairs an outbound with a return, both meeting all other filters
- Filters: `airline`, `minPrice`, `maxPrice`, `departureTimeFrom`, `departureTimeTo`, `class` (already in slice 02 but now enforced against the seat map's class distribution)
- Pagination applies to pairs (for round-trip) or flights (for one-way)
- Sort: by total price ascending (default), by departure time ascending (optional)

## OUT of scope
- Multi-city itineraries (3+ legs) — spec is silent, treat as out of scope
- Airline alliances / partner flights
- Connecting/layover flights (spec mentions them in requirements but we deferred to DESIGN — flag if DESIGN decides to add)

## Learning hypothesis
**Disproves if fails**: Round-trip search is two independent one-way searches joined in-memory — no round-trip-specific storage or logic needed.
**Confirms if succeeds**: We can keep search simple and just compose.

## Acceptance criteria
1. `GET /flights/search?origin=LAX&destination=NYC&departureDate=2026-06-01&returnDate=2026-06-08` returns paired outbound+return flights, where each pair is compatible (return dep > outbound arrival).
2. `airline=AA` restricts results to that airline (exact match on IATA code).
3. `minPrice=100&maxPrice=500` restricts results to flights whose indicative total falls in that range.
4. `departureTimeFrom=09:00&departureTimeTo=17:00` filters by the local departure time window.
5. Filters compose (AND) correctly and commutatively.
6. Round-trip pagination paginates pairs, not individual flights; pagination metadata distinguishes pair count from flight count.
7. Response p95 stays <500ms at the slice 02 catalog size.

## Dependencies
- Slice 02 (search + catalog exists)
- Slice 05 (indicative prices include surcharges, so min/maxPrice filters are meaningful)

## Effort estimate
4–6 hours.

## Pre-slice SPIKE
None required.

## Open question
- **Round-trip pair definition**: the spec doesn't define. Default: an outbound + return is a "pair" when return.origin == outbound.destination, return.departure > outbound.arrival + 2h buffer, and (if class provided) both legs have the class available. Flag for DESIGN if user wants richer semantics.

## Dogfood moment
Developer searches a realistic LAX↔NYC round-trip with a price range and departure-window filter, gets a sensible paired result set, and can sort it.
