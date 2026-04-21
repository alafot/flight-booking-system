Feature: Milestone 02 — Flight catalog and search
  Traveler can search a realistic catalog with pagination and per-field validation.
  Driving adapter: GET /flights/search (FastAPI).

  Background:
    Given the clock is frozen at 2026-04-25 10:00:00 UTC
    And the flight catalog is seeded with 200 flights across 20 routes, 5 airlines, 30 dates, 3 classes

  @kpi
  Scenario: Filter by origin, destination, and departure date
    When the traveler searches flights from LAX to NYC on 2026-06-01
    Then the response status is 200
    And every returned flight has origin "LAX", destination "NYC", and departure date 2026-06-01

  @pending
  Scenario: Pagination defaults and maximum
    When the traveler searches flights from LAX to NYC on 2026-06-01 requesting page 1
    Then the response contains at most 20 flights
    And the pagination metadata reports the total count and current page
    When the traveler searches with page size 50
    Then the response still contains at most 20 flights

  @pending
  Scenario Outline: Invalid input returns 400 with a per-field error
    When the traveler searches flights with <field> = "<bad_value>"
    Then the response status is 400
    And the response body lists an error for field "<field>"

    Examples:
      | field          | bad_value    |
      | origin         | XX           |
      | origin         | LosAngeles   |
      | destination    | 123          |
      | departureDate  | not-a-date   |
      | passengers     | 0            |
      | passengers     | 10           |
      | class          | COACH        |

  Scenario: Empty result set returns 200 with an empty array
    When the traveler searches flights from LAX to ABZ on 2026-06-01
    Then the response status is 200
    And the response contains zero flights
    And the pagination metadata reports a total count of 0

  @pending @kpi
  Scenario: Search p95 latency budget
    Given the seeded catalog is loaded
    When the traveler runs 100 sequential searches with varied parameters
    Then the p95 response time is under 500 milliseconds
