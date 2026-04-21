Feature: Milestone 03 — Seat map and seat-specific commit
  Traveler can see the cabin layout with per-seat status and book a named seat.
  Driving adapters: GET /flights/{id}/seats, POST /bookings.

  Background:
    Given the clock is frozen at 2026-04-25 10:00:00 UTC
    And the flight "FL-LAX-NYC-0800" has the default 30x6 cabin (rows 1-2 First, 3-6 Business, 7-30 Economy)

  Scenario: Seat map returns 180 seats with correct class assignment
    When the traveler requests the seat map for flight "FL-LAX-NYC-0800"
    Then the response status is 200
    And the response contains 180 seats
    And seat "1A" is in class "FIRST"
    And seat "5C" is in class "BUSINESS"
    And seat "12C" is in class "ECONOMY"

  @pending
  Scenario: Booking a non-existent seat
    When the traveler books flight "FL-LAX-NYC-0800" with seat "99Z"
    Then the response status is 400
    And the response body cites "unknown seat"

  @pending
  Scenario: Booking an already-OCCUPIED seat
    Given seat "12C" is OCCUPIED on flight "FL-LAX-NYC-0800"
    When the traveler books flight "FL-LAX-NYC-0800" with seat "12C"
    Then the response status is 409
    And the response body cites "seat already booked"

  @pending
  Scenario: Booking a BLOCKED seat
    Given seat "14A" is BLOCKED for maintenance on flight "FL-LAX-NYC-0800"
    When the traveler books flight "FL-LAX-NYC-0800" with seat "14A"
    Then the response status is 409
    And the response body cites "seat not for sale"

  Scenario: Seat map reflects a newly-committed booking
    Given seat "12C" is AVAILABLE on flight "FL-LAX-NYC-0800"
    When the traveler successfully books seat "12C" on that flight
    And the traveler requests the seat map for "FL-LAX-NYC-0800"
    Then seat "12C" is reported as OCCUPIED
