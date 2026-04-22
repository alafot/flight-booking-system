# Slice 04 — Dynamic Pricing Engine (Appendix B)

## Goal (one sentence)
Replace the base-fare-only price with the full `base × demand × time × day` formula from Appendix B, as a pure deterministic function.

## IN scope
- Pure pricing function: `price(baseFare, occupancyPct, daysBeforeDeparture, departureDayOfWeek) → decimal`
- All three multiplier tables from Appendix B encoded as explicit rule tables (not magic numbers inline)
- Applied to indicative search prices (slice 02 upgraded) and to quote prices (slice 06 later)
- Exact match for the three Appendix B worked examples to the cent

## OUT of scope
- Seat surcharges (slice 05)
- Taxes and fees (slice 05)
- Group discount, promo codes (slice 12)
- Price *quote TTL* and audit (slice 06)
- Currency conversion (slice 12)

## Learning hypothesis
**Disproves if fails**: Pricing can be a pure function with no hidden state — deterministic for given inputs, property-based-testable.
**Confirms if succeeds**: Audit and quote-TTL slices are trivially additive because the formula itself is stateless.

## Acceptance criteria
1. `price(299, 0.00, 30, Tuesday)` = 228.74 USD (Appendix B example 1; rounding to 2 dp with banker's rounding).
2. `price(299, 0.80, 2, Friday)` = 897.00 USD (Appendix B example 2).
3. `price(299, 0.98, 0, Sunday)` = 1944.00 USD (Appendix B example 3).
4. Property-based test: for any valid input, `price` returns a positive decimal and never depends on the current wall clock (all time inputs are parameters).
5. Rule-table change (e.g., tweaking Friday multiplier) touches exactly one location in code.
6. Boundary inputs (0%, 30%, 31%, 100% occupancy; 60 days; same-day) pick the correct tier on both sides of each boundary.

## Dependencies
- Slice 02 (search exists and needs indicative prices)

## Effort estimate
4–6 hours. The heart is the rule-table + boundary testing discipline.

## Pre-slice SPIKE
Optional 15-min property-based-testing SPIKE if team is new to Hypothesis — but not blocking. Required: agree on rounding rule up front (half-even vs half-up) with the user.

## Open question to resolve before committing
- **Rounding**: spec examples compute to the cent. What rule? Recommend banker's rounding (half-even), explicit, documented in the function signature.
- **Boundary inclusivity**: "31-50%" — is 31% or 50% in that bucket? Recommend: left-inclusive, right-exclusive (`[31%, 51%)`), with the 0–30% bucket being `[0%, 31%)`.

## Dogfood moment
Developer runs `python -c "from pricing import price; print(price(299, 0.0, 30, 'Tue'))"` and sees 228.74 — the Appendix B example value — exactly.
