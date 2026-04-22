Feature: Book a flight end-to-end
  As a traveler
  I want to search, pick a seat, see a transparent price, and commit a booking
  So that I can confirm my trip with confidence and a reference number I trust.

  Background:
    Given the system has flight "FL-LAX-NYC-0800" scheduled from LAX to NYC on 2026-06-01 at 08:00
    And the aircraft has 30 rows of 6 seats (A–F) configured as Economy/Business/First per the cabin layout
    And the base fare for this flight in Economy is 299 USD
    And today is 2026-04-25

  # --- Happy path (covers all 6 journey steps) ---
  Scenario: Happy path LAX to NYC — single passenger economy
    When I GET /flights/search with origin=LAX, destination=NYC, departureDate=2026-06-01, passengers=1, class=ECONOMY
    Then the response status is 200
    And the response body contains flight "FL-LAX-NYC-0800" with duration, stops, and indicative price
    When I GET /flights/FL-LAX-NYC-0800/seats
    Then the seat map returns 180 seats with per-seat status and per-seat surcharge
    And seat "12C" is AVAILABLE
    When I POST a price quote for flight "FL-LAX-NYC-0800", seats ["12C"], passengers=1
    Then the response contains a quoteId, a price breakdown (base, taxes, fees, total), a currency, and an expiry 30 minutes in the future
    And an audit record is written keyed by the quoteId
    When I POST a seat hold for lockId against ["12C"] with the quoteId
    Then the response contains a seatLock with expiresAt 10 minutes in the future
    When I POST /bookings with quoteId, seatLock, passengerDetails, and a mock paymentToken
    Then the response status is 201
    And the response contains a booking reference
    And the booking status is CONFIRMED
    And seat "12C" is now OCCUPIED in the seat map
    And a confirmation email is queued for the passenger

  # --- Error paths mapped from spec "Edge Cases" ---

  Scenario: Double booking — two sessions race for the last seat (spec edge case 1)
    Given only seat "30F" remains AVAILABLE on flight "FL-LAX-NYC-0800"
    And session A and session B have both quoted seat "30F"
    When session A POSTs a seat hold for "30F"
    And session B POSTs a seat hold for "30F" concurrently
    Then exactly one session receives a successful seatLock
    And the other session receives HTTP 409 with "seat unavailable"
    And the seat map reports "30F" as unavailable to all other sessions

  Scenario: Price change between quote and booking completion (spec edge case 2)
    Given I have a valid quote Q1 for flight "FL-LAX-NYC-0800" with total 299.00 USD
    And the flight's occupancy subsequently crosses the 86%+ threshold (doubling the demand multiplier)
    When I POST /bookings with Q1 within Q1's 30-minute validity window
    Then the booking is created at 299.00 USD (the quoted price, not the current price)
    When I POST /bookings with Q1 after its 30-minute validity window has expired
    Then the response status is 410 Gone
    And the response instructs me to re-quote

  Scenario: Flight cancellation while bookings exist (spec edge case 3)
    Given I have a CONFIRMED booking B1 on flight "FL-LAX-NYC-0800"
    When the operator marks flight "FL-LAX-NYC-0800" as CANCELLED
    Then booking B1 moves to status CANCELLED_BY_OPERATOR
    And a full refund is owed (no cancellation fee applied, since the traveler did not cancel)
    And a cancellation notice is queued for the passenger
    And an audit record for the refund is written

  Scenario: Invalid passenger data (spec edge case 4)
    Given I have a valid quote and a valid seat lock for an international flight
    When I POST /bookings without passport information for any passenger
    Then the response status is 422
    And the response body identifies the missing fields by passenger index
    And no booking is created
    And the seat lock remains held until its TTL

  Scenario: Payment failure during booking commit (spec edge case 5)
    Given I have a valid quote Q1 and a valid seat lock L1
    When I POST /bookings with a paymentToken that the mock payment gateway rejects
    Then the response status is 402
    And no booking is created
    And the seat lock L1 remains valid until its TTL so I may retry with a different paymentToken
    And an audit record for the failed payment attempt is written

  Scenario: Selected seat becomes unavailable before hold (spec edge case 6)
    Given I quoted seat "12C" five minutes ago
    And another session has since locked seat "12C"
    When I POST a seat hold for "12C"
    Then the response status is 409
    And the response body suggests alternative AVAILABLE seats in the same row and class

  # --- Business rule enforcement ---

  Scenario: Booking blocked within 2 hours of departure
    Given flight "FL-LAX-NYC-0800" departs in 90 minutes
    When I POST /bookings on that flight
    Then the response status is 409
    And the response body cites "minimum booking time: 2 hours before departure"

  Scenario: Booking blocked when flight is 95%+ full
    Given flight "FL-LAX-NYC-0800" has 171 of 180 seats occupied (95%)
    When I POST a price quote for any seat on that flight
    Then the response status is 423
    And the response body cites "capacity management: sales closed at 95% full"

  Scenario: Cancellation fee by window
    Given I have a CONFIRMED booking B1 on flight "FL-LAX-NYC-0800" with total 400 USD
    When I DELETE /bookings/B1 more than 24 hours before departure
    Then the refund is 360 USD (10% fee applied)
    And the booking status is CANCELLED_BY_TRAVELER
    When I DELETE /bookings/B2 between 2 and 24 hours before departure
    Then the refund is 50% of the total
    When I DELETE /bookings/B3 less than 2 hours before departure
    Then the refund is 0
    And the response explains "no refund inside 2 hours"

  Scenario: Dynamic pricing formula — empty Tuesday flight 30 days out
    Given flight "FL-LAX-NYC-0800" is at 0% occupancy
    And its departure is on a Tuesday
    And today is 30 days before departure
    And base fare is 299 USD
    When I request a price quote for 1 economy seat with no seat surcharge
    Then the total base-before-taxes equals 299 × 1.00 × 0.90 × 0.85 = 228.74 USD (rounded per currency rules)

  Scenario: Seat-specific pricing — exit row economy
    Given flight "FL-LAX-NYC-0800" has seat "14A" in the exit row
    When I request a price quote for seat "14A" in Economy
    Then the seat surcharge returned is +35 USD
    And this surcharge is included in the total in the price breakdown

  Scenario: Group booking discount threshold
    Given I request a price quote for 5 economy seats on flight "FL-LAX-NYC-0800"
    Then the price breakdown includes a "group booking discount" line
    When I request a price quote for 4 economy seats on the same flight
    Then the price breakdown does NOT include a group booking discount
