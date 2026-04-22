# Flight Booking System — Product Vision

## One-line vision

A RESTful flight booking service that lets travelers search flights, pick specific seats, see transparent all-in pricing, and manage bookings end-to-end — with honest dynamic pricing, safe concurrency, and auditable money decisions.

## Why this exists

The spec (`Flight-Booking-System.pdf`) frames this as a coding exercise, but the product it describes is a complete booking core: the backend of record for a traveler-facing booking funnel. The value is *deciding and committing a purchase with confidence* — the user must trust that the price they see is the price they'll pay, that the seat they pick is actually theirs, and that changes/cancellations behave predictably.

## Target user (primary)

**The Traveler** — a retail customer booking 1–9 seats for themselves or their travel group. Not a travel agent, not a corporate desk. They interact through an HTTP API (this system) that a UI or CLI will front in future work.

Secondary users implied by the spec: **operators** who block seats for maintenance, and **auditors** who inspect pricing decisions.

## Primary outcome

A traveler can go from "I want to fly LAX→NYC on date X" to a confirmed booking reference in under one session, with a price they understood before they committed and a seat they specifically chose.

## Scope boundaries (what this product is NOT)

- Not a UI. All endpoints return JSON; a frontend is out of scope.
- Not a real payment processor. Payment is mocked — the contract is the interesting part.
- Not a real database. In-memory persistence by design; durability is not a goal of this iteration.
- Not multi-aircraft. One 30×6 cabin configuration (Economy/Business/First) is the only layout.
- Not multi-currency *settlement*. USD is the book currency; real-time conversion exists only for display.

## Key constraints (from spec)

- Flight search < 2s; booking creation < 5s; support ≥10 concurrent bookings.
- Price quotes valid for 30 minutes.
- Seat locks hold for 10 minutes during the booking funnel.
- All pricing decisions must be logged for audit.

## What success looks like

- Happy path LAX→NYC end-to-end works (search → seats → price → book → confirm).
- The six spec-named edge cases (double booking, price drift, flight cancellation, invalid data, payment failure, seat unavailable) all return correct, non-corrupting responses.
- Every booked seat is booked exactly once, even under concurrent attempts on the last seat.
- Every quoted price can be explained from a logged audit record.

## Outstanding vision-level uncertainties

- How are seat locks released on client abandonment? (Expiry is obvious; explicit release endpoint is implied but not mandated.)
- Is "overbooking by 5% for economy" a system-initiated behaviour or only a capacity-ceiling relaxation? The spec says "allow", not "auto".
- "Real-time currency conversion" — from what source? Treated as a mocked FX port for this iteration.
