Feature: Milestone 06 — Quote TTL and audit log
  Quote persists 30 minutes; commit honors the quoted price; every pricing decision is audited.
  Driving adapters: POST /quotes, POST /bookings.

  Background:
    Given the clock is frozen at 2026-04-25 10:00:00 UTC
    And a flight "FL-LAX-NYC-0800" with known base fare and pricing context

  @kpi
  Scenario: Quote expires 30 minutes after creation
    When the traveler creates a quote for seat "12C"
    Then the response contains an expiresAt exactly 30 minutes in the future
    And the audit log contains a "QuoteCreated" event for that quote

  @pending @kpi
  Scenario: Commit within 30 minutes honors the quoted total even if demand changed
    When the traveler creates a quote with total 228.74 USD
    And the flight's occupancy subsequently jumps into the 86%+ bracket
    And the clock advances by 20 minutes
    And the traveler commits the booking using that quote id
    Then the response status is 201
    And the booking's total_charged is exactly 228.74 USD
    And the audit log contains a "BookingCommitted" event referencing the quote id and total

  @pending @kpi
  Scenario: Commit after TTL returns 410 Gone
    When the traveler creates a quote
    And the clock advances by 31 minutes
    And the traveler commits the booking using that quote id
    Then the response status is 410
    And the response body cites "quote expired"
    And no "BookingCommitted" event is written to the audit log

  @pending
  Scenario: Commit with an unknown quote id returns 404
    When the traveler commits a booking with quoteId "UNKNOWN"
    Then the response status is 404
    And the response body cites "quote not found"

  @kpi @adapter-integration
  Scenario: Audit log replay reconstructs the committed total
    Given audit events QuoteCreated and BookingCommitted were written during a successful booking
    When the replay utility reads the audit log
    Then for each BookingCommitted event, re-running pricing.price with the matching QuoteCreated inputs produces the same total
