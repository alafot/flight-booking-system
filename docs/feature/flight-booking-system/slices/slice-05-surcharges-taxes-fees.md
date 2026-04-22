# Slice 05 — Seat Surcharges + Taxes + Fees (Appendix A)

## Goal (one sentence)
Return a full `priceBreakdown` on every quote: base fare, per-seat surcharges (Appendix A), taxes, fees, and computed total.

## IN scope
- Apply Appendix A surcharges per seat class and seat type (exit row, front section, aisle/window, middle seat discount, etc.)
- Flat tax rule set: "domestic" vs "international" tax rates, configurable
- Ancillary fees: baggage (flat), seat selection fee (per-seat, already covered by Appendix A), meal preference (flat) — defined as a configurable table
- `priceBreakdown` response shape: `{ baseFare, seatSurcharges[], demandMultiplier, timeMultiplier, dayMultiplier, taxes, fees, total, currency }`
- Display currency: USD only in this slice

## OUT of scope
- Real tax engine (we encode 2 flat rates only)
- Promo codes / group discount (slice 12)
- Quote TTL / audit log (slice 06)
- Multiple currencies (slice 12)

## Learning hypothesis
**Disproves if fails**: The breakdown contract is additive — new fee categories don't touch the multiplier formula.
**Confirms if succeeds**: Slice 12's discount/promo additions will only add lines to the response, not rework existing math.

## Acceptance criteria
1. Economy seat 14A (exit row) returns `seatSurcharges: [{ seat: "14A", amount: 35.00 }]`.
2. Economy middle seat (e.g., 8B) returns `amount: -5.00`.
3. Business class "Lie-Flat Suite" returns `+200.00`; aisle-access returns `+75.00`.
4. `total` equals `baseFare × demandMultiplier × timeMultiplier × dayMultiplier + Σ seatSurcharges + taxes + fees`.
5. International route flight applies the international tax rate; domestic applies the domestic rate.
6. Every number in the breakdown appears in the response (no hidden computations); a reviewer can reproduce `total` on paper.

## Dependencies
- Slice 04 (dynamic pricing function exists)

## Effort estimate
4–6 hours. Seat-classification rules (which seats are "exit row", "front section", etc.) need explicit mapping.

## Pre-slice SPIKE
None required. Note that "exit row" location depends on the DESIGN cabin layout — reconcile with the slice 03 layout first.

## Open question
- **Seat classification source of truth**: exit row rows and "bulkhead" depend on cabin layout. Agree with DESIGN: does the cabin fixture declare these per-seat, or does a rule infer them from row number?

## Dogfood moment
Traveler-facing JSON shows every component of the total — a developer can `jq` the response and explain any price to a customer.
