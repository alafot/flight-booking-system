Feature: Milestone 05 — Price breakdown with surcharges, taxes, and fees
  Full breakdown per Appendix A surcharges plus domestic/international taxes.
  Driving adapter: POST /quotes.

  Background:
    Given the clock is frozen at 2026-04-25 10:00:00 UTC
    And a flight "FL-LAX-NYC-0800" with base fare 299 USD, departing Tuesday with 0% occupancy, 30 days out

  @kpi
  Scenario: Exit row economy seat surcharge (+$35)
    Given seat "14A" in Economy has kind "EXIT_ROW"
    When the traveler quotes seat "14A"
    Then the response status is 200
    And the breakdown's seat_surcharges list contains exactly { seat: "14A", amount: 35.00 }

  @kpi
  Scenario: Middle economy seat discount (-$5)
    Given seat "12B" in Economy has kind "MIDDLE"
    When the traveler quotes seat "12B"
    Then the breakdown's seat_surcharges list contains { seat: "12B", amount: -5.00 }

  @kpi
  Scenario: Business lie-flat suite surcharge (+$200)
    Given seat "3A" in Business has kind "LIE_FLAT_SUITE"
    When the traveler quotes seat "3A"
    Then the breakdown's seat_surcharges list contains { seat: "3A", amount: 200.00 }

  Scenario: Total equals the arithmetic of all components
    Given seat "14A" in Economy has kind "EXIT_ROW"
    When the traveler quotes seat "14A"
    Then the total equals base_fare * demand_multiplier * time_multiplier * day_multiplier + surcharges + taxes + fees
    And the computation can be reproduced on paper from the response fields

  @kpi
  Scenario: Domestic vs international tax rates
    Given flight "FL-LAX-NYC-0800" is marked "domestic"
    When the traveler quotes one seat
    Then the taxes line equals the configured domestic rate times the base

    Given flight "FL-LAX-LHR-2100" is marked "international"
    When the traveler quotes one seat on that flight
    Then the taxes line equals the configured international rate times the base

  Scenario: Breakdown precision round-trips
    When the traveler quotes any seat on any flight
    Then every monetary value in the response is a string with exactly 2 decimal places
    And parsing each back as Decimal yields the same quantized value
