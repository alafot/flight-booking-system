Feature: Milestone 08 — Round-trip search and filters
  Return date pairs outbound+return; airline, price range, and departure-time filters.
  Driving adapter: GET /flights/search.

  Background:
    Given the clock is frozen at 2026-04-25 10:00:00 UTC
    And a seeded catalog with outbound flights on 2026-06-01 and return flights on 2026-06-08

  Scenario: Round-trip search returns compatible outbound+return pairs
    When the traveler searches LAX to NYC on 2026-06-01 with returnDate 2026-06-08
    Then every result is a pair where return.origin equals outbound.destination
    And every pair has return.departure at least 2 hours after outbound.arrival

  @pending
  Scenario: Airline filter restricts by IATA code
    When the traveler searches LAX to NYC on 2026-06-01 with airline "AA"
    Then every returned flight has airline "AA"

  @pending
  Scenario: Price range filter uses the indicative total inclusive of surcharges
    When the traveler searches LAX to NYC on 2026-06-01 with minPrice 200 and maxPrice 500
    Then every returned flight's indicative total is between 200 and 500 inclusive

  @pending
  Scenario: Departure time window filter
    When the traveler searches LAX to NYC on 2026-06-01 with departureTimeFrom 09:00 and departureTimeTo 17:00
    Then every returned flight departs between 09:00 and 17:00 local time

  @pending
  Scenario: Filters compose (AND) and are commutative
    When the traveler searches with airline "AA" and maxPrice 500
    And the traveler searches with maxPrice 500 and airline "AA"
    Then both responses return identical result sets

  Scenario: Round-trip pagination paginates pairs
    When the traveler searches a round-trip on a seeded catalog with 50 candidate pairs
    Then the response contains at most 20 pairs
    And pagination metadata reports both pairCount and flightCount (flightCount = 2 * pairCount)
