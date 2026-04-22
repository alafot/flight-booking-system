# Slice 01 — Walking Skeleton

## Goal (one sentence)
Ship one end-to-end booking through real HTTP, proving the Python stack wires together before we invest in business logic.

## IN scope
- One hardcoded flight (LAX→NYC, fixed date/time)
- `GET /flights/search` returning exactly that flight when origin=LAX, destination=NYC, date matches; empty otherwise
- Flat base-fare price (no multipliers, no surcharges, no taxes)
- `POST /bookings` accepting `{ flightId, seatId, passenger }` — seatId is a plain string, no validation beyond non-empty
- `GET /bookings/{id}` returning the booking JSON
- In-memory repositories (dicts)
- Basic JSON request validation + HTTP status codes (200, 201, 400, 404)

## OUT of scope
- Dynamic pricing
- Seat map / seat classes / surcharges
- Seat locking or concurrency safety
- Filters, pagination, round-trip, multi-passenger
- Modifications, cancellations, audit log, email
- Authentication

## Learning hypothesis
**Disproves if fails**: Our chosen layering (HTTP adapter → service → repository, domain in the middle) wires together cleanly in Python with the framework we picked.
**Confirms if succeeds**: We can add behavior in subsequent slices without structural rework.

## Acceptance criteria
1. `curl GET /flights/search?origin=LAX&destination=NYC&departureDate=2026-06-01` returns HTTP 200 with a JSON array of exactly one flight.
2. `curl POST /bookings` with that flight returns HTTP 201 and a booking reference.
3. `curl GET /bookings/{ref}` returns HTTP 200 with the booking.
4. The layering shows HTTP → service → repo — no business logic in the HTTP layer.
5. End-to-end test exercises the real HTTP endpoints, not service classes directly.

## Dependencies
None (first slice).

## Effort estimate
4–6 hours. Reference class: "hello-world HTTP API with one resource and in-memory store" in Python — well-known, low variance.

## Pre-slice SPIKE
Not required. If the team is new to the chosen framework (Flask/FastAPI/Starlette), a 30-min SPIKE to confirm route+validation+JSON response works is enough.

## Dogfood moment
Developer can book a flight end-to-end from the command line in one session.
