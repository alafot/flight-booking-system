# Shared Artifacts Registry — flight-booking-system

Every variable passed between journey steps is listed here with its producer, consumers, and the single source of truth. If an artifact has no single source, that's a DESIGN-time bug — flag it.

| Artifact | Produced at step | Consumed at step(s) | Single source of truth | Notes |
|---|---|---|---|---|
| `${flightId}` | `step.search` | `step.inspect-seats`, `step.quote-price` | Flight repository (in-memory) | Opaque string; format TBD in DESIGN. |
| `${selectedSeats}` | client (UI) after `step.inspect-seats` | `step.quote-price`, `step.hold-seats` | Client-sent, server-validated against live seat map | Seat IDs like `"12C"`. |
| `${passengers}` | client input at `step.search` or later | `step.quote-price`, `step.commit` | Client-sent | Integer 1–9 (spec: max 9 per booking). |
| `${class}` | client input at `step.search` or `step.quote-price` | `step.quote-price`, price engine | Client-sent; validated against seats' class | Enum: `ECONOMY \| BUSINESS \| FIRST` (spec section 2; Premium Economy from Appendix A is deferred). |
| `${seatMap}` | `step.inspect-seats` | (display only, feeds client's seat selection) | Computed from Flight + SeatLock + Booking state | Must reflect locks held by *other* sessions as unavailable. |
| `${quoteId}` | `step.quote-price` | `step.commit` | Price quote store (in-memory, 30-min TTL) | Opaque; one quote per `(flight, seats, passengers, client)` tuple. |
| `${priceBreakdown}` | `step.quote-price` | client display; `step.commit` for match-check | Audit log + price quote store | Fields: `baseFare`, `seatSurcharges[]`, `demandMultiplier`, `timeMultiplier`, `dayMultiplier`, `taxes`, `fees`, `discounts[]`, `total`, `currency`, `quoteExpiry`. |
| `${seatLock}` | `step.hold-seats` | `step.commit` | Seat lock store (in-memory, 10-min TTL) | `{ lockId, flightId, seats[], expiresAt }`. |
| `${paymentToken}` | client → `step.commit` | `step.commit` payment call | Mock payment adapter | Opaque token representing a "card on file". |
| `${bookingReference}` | `step.commit` | `step.manage`, confirmation email | Booking repository | Human-readable, unique (e.g., 6-char alphanumeric). |
| `${auditRecord}` | `step.quote-price`, `step.commit`, `step.manage` (cancel/modify) | (read by auditors, not journey steps) | Append-only audit log (in-memory) | One record per pricing decision and per state-changing operation. |
| `${refundBreakdown}` | `step.manage` (cancel) | returned to client; audit log | Computed from Booking + cancellation rule window + audit log | Fields: `refundableAmount`, `feeApplied`, `feePercent`, `reason`. |

## Gaps flagged for DESIGN

- **Client identity for quoteId binding**: should `${quoteId}` be bindable to a specific client/session, or freely transferable? Spec is silent. Default recommendation: quote is bound to the same client that requested it (anti-abuse).
- **Seat lock ownership**: same question — is a lock scoped to a session or transferable? Default: session-scoped.
- **Audit log read interface**: no read endpoint specified. Defer to DESIGN if auditors need a read path.
