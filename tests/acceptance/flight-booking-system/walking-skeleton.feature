Feature: Walking skeleton — book a flight end-to-end
  As a traveler, I want to complete one booking through the real HTTP API
  so that the whole stack (HTTP → services → domain → in-memory adapters) is proven to work end-to-end.

  Driving adapter: FastAPI app at http://testserver, invoked via httpx TestClient.
  Driven adapters: InMemoryFlightRepository, InMemoryBookingRepository,
  MockPaymentGateway, MockEmailSender, FrozenClock, DeterministicIdGenerator,
  InMemoryAuditLog.

  Background:
    Given the clock is frozen at 2026-04-25 10:00:00 UTC
    And the flight catalog has one flight "FL-LAX-NYC-0800" from LAX to NYC departing 2026-06-01 at 08:00, base fare 299 USD
    And seat "12C" in Economy is AVAILABLE on that flight

  @walking_skeleton @real-io @driving_adapter
  Scenario: Search, book, retrieve — end-to-end through HTTP
    When the traveler searches flights from LAX to NYC on 2026-06-01
    Then the response status is 200
    And the response body contains the flight "FL-LAX-NYC-0800"
    When the traveler books flight "FL-LAX-NYC-0800" with seat "12C" for passenger "Jane Doe" using payment token "mock-ok"
    Then the response status is 201
    And the response contains a booking reference
    And the booking status is "CONFIRMED"
    When the traveler retrieves the booking using its reference
    Then the response status is 200
    And the response shows seat "12C" on flight "FL-LAX-NYC-0800"
    And the confirmation email queue contains one email for "Jane Doe"
    And the audit log contains a "BookingCommitted" event for that reference

  @real-io @adapter-integration
  Scenario: JsonlAuditLog persists events to the real filesystem
    Given an audit log at a temporary JSON-lines file
    When the system writes 3 audit events of types "QuoteCreated", "BookingCommitted", "PaymentFailed"
    Then the file exists on disk
    And the file contains exactly 3 JSON lines
    And each line parses as a JSON object with a "type" field matching the written type
    And reading the audit log back returns the same 3 events in order
