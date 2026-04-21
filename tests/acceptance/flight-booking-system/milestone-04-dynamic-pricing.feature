Feature: Milestone 04 — Dynamic pricing engine (Appendix B)
  Price = base x demand-multiplier x time-multiplier x day-multiplier, rounded half-even.
  Driving adapter: POST /quotes.

  @kpi
  Scenario: Appendix B example 1 — empty Tuesday flight, 30 days ahead
    Given the clock is frozen at 2026-05-03 10:00:00 UTC
    And a flight departing Tuesday 2026-06-02 with 0% occupancy and base fare 299 USD
    When the traveler quotes one economy seat with no seat surcharge
    Then the response status is 200
    And the total is exactly 228.74 USD
    And the breakdown shows demand_multiplier 1.00, time_multiplier 0.90, day_multiplier 0.85

  @kpi
  Scenario: Appendix B example 2 — 80% full Friday flight, 2 days ahead
    Given the clock is frozen at 2026-05-27 10:00:00 UTC
    And a flight departing Friday 2026-05-29 with 80% occupancy and base fare 299 USD
    When the traveler quotes one economy seat with no seat surcharge
    Then the total is exactly 897.00 USD
    And the breakdown shows demand_multiplier 1.60, time_multiplier 1.50, day_multiplier 1.25

  @kpi
  Scenario: Appendix B example 3 — near-full Sunday flight, same-day booking
    Given the clock is frozen at 2026-05-31 08:00:00 UTC
    And a flight departing Sunday 2026-05-31 at 14:00 with 98% occupancy and base fare 299 USD
    When the traveler quotes one economy seat with no seat surcharge
    Then the total is exactly 1944.00 USD
    And the breakdown shows demand_multiplier 2.50, time_multiplier 2.00, day_multiplier 1.30

  Scenario Outline: Boundary inputs land in the correct bucket
    Given a flight with <occupancy>% occupancy and base fare 299 USD
    When the traveler quotes at <days> days before departure on <day_of_week>
    Then the demand_multiplier is <expected_demand>
    And the time_multiplier is <expected_time>
    And the day_multiplier is <expected_dow>

    Examples:
      | occupancy | days | day_of_week | expected_demand | expected_time | expected_dow |
      | 0         | 60   | MON         | 1.00            | 0.85          | 0.90         |
      | 30        | 21   | TUE         | 1.00            | 0.90          | 0.85         |
      | 31        | 20   | WED         | 1.15            | 1.00          | 0.85         |
      | 50        | 7    | THU         | 1.15            | 1.00          | 0.95         |
      | 51        | 6    | FRI         | 1.35            | 1.20          | 1.25         |
      | 85        | 2    | SAT         | 1.60            | 1.50          | 1.15         |
      | 86        | 1    | SUN         | 2.00            | 1.50          | 1.30         |
      | 100       | 0    | SUN         | 2.50            | 2.00          | 1.30         |

  Scenario: Rule table is the single source of truth for multipliers
    When all demand multipliers are read from the rule table
    Then the values match Appendix B exactly
    And changing any multiplier requires editing only one location in the code
