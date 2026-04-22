Feature: Milestone 07 — Seat locking and concurrent-booking safety
  Exactly-one-winner under ten concurrent bookings on the same seat.
  Driving adapters: POST /seat-locks, POST /bookings.

  Background:
    Given the clock is frozen at 2026-04-25 10:00:00 UTC
    And a flight "FL-LAX-NYC-0800" where seat "30F" is the only remaining AVAILABLE seat

  Scenario: Single session acquires a lock on an available seat
    When session "S1" requests a lock on seat "30F" for flight "FL-LAX-NYC-0800"
    Then the response status is 201
    And the response contains a lock id and an expiresAt 10 minutes in the future

  Scenario: A second session sees the locked seat as unavailable
    Given session "S1" holds a valid lock on seat "30F"
    When session "S2" requests the seat map for "FL-LAX-NYC-0800"
    Then seat "30F" is reported as unavailable to session "S2"

  @kpi
  Scenario: Ten concurrent lock requests on the same seat — exactly one winner
    When ten sessions concurrently request a lock on seat "30F"
    Then exactly one session receives HTTP 201
    And the other nine sessions receive HTTP 409 with "seat unavailable"
    And zero sessions receive a 500

  @pending @kpi @real-io
  Scenario: Race harness — 100 trials, zero double-bookings
    When the race-last-seat harness runs 100 trials, each with 10 threads competing for one seat
    Then every trial produces exactly one winner and nine rejections
    And over 100 trials, the count of "double-booking" outcomes is 0

  Scenario: Lock auto-expires after 10 minutes
    Given session "S1" holds a lock on seat "30F" acquired at 10:00:00
    When the clock advances to 10:10:01
    And session "S2" requests a lock on seat "30F"
    Then session "S2" receives HTTP 201 with a new lock

  Scenario: Commit with expired lock returns 410 Gone
    Given session "S1" holds a lock on seat "30F" and an associated valid quote
    When the clock advances by 11 minutes
    And session "S1" commits a booking using the expired lock
    Then the response status is 410
    And the response body cites "seat lock expired"

  Scenario: Payment failure preserves the seat lock for retry
    Given session "S1" holds a valid lock on seat "30F" and a valid quote
    When session "S1" commits with a paymentToken that the mock rejects
    Then the response status is 402
    And the lock on seat "30F" is still valid when the clock is unchanged
    And an audit "PaymentFailed" event is written
