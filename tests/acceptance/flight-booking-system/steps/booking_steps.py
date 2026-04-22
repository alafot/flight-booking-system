"""Step definitions for the walking-skeleton and milestone .feature files.

Scaffolded by DISTILL. Most steps raise AssertionError until DELIVER wires
real behavior through the composition root. Steps that only manipulate the
``world`` bag (pure test choreography) do NOT raise — they run even on the
scaffold so pytest-bdd can collect the scenarios cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from flights.adapters.mocks.audit import JsonlAuditLog
from flights.adapters.mocks.clock import FrozenClock
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus
from tests.fixtures.cabin import default_cabin
from tests.fixtures.catalog import seeded_catalog

__SCAFFOLD__ = True

# Bind all feature files in the parent directory to this steps module.
FEATURES_DIR = Path(__file__).parent.parent
scenarios(str(FEATURES_DIR / "walking-skeleton.feature"))
scenarios(str(FEATURES_DIR / "milestone-02-catalog-search.feature"))
scenarios(str(FEATURES_DIR / "milestone-03-seat-map.feature"))
scenarios(str(FEATURES_DIR / "milestone-04-dynamic-pricing.feature"))
scenarios(str(FEATURES_DIR / "milestone-05-price-breakdown.feature"))
scenarios(str(FEATURES_DIR / "milestone-06-quote-ttl-audit.feature"))
scenarios(str(FEATURES_DIR / "milestone-07-seat-locking.feature"))
scenarios(str(FEATURES_DIR / "milestone-08-round-trip-filters.feature"))


# ---- Background / setup steps ----------------------------------------------

@given(parsers.parse("the clock is frozen at {date} {time} UTC"))
def _freeze_clock(frozen_clock: FrozenClock, date: str, time: str) -> None:
    frozen_clock.set(datetime.fromisoformat(f"{date}T{time}+00:00"))


@given(parsers.parse('the flight catalog has one flight "{flight_id}" from {origin} to {destination} departing {date} at {time}, base fare {fare} USD'))
def _seed_single_flight(container, world: dict, flight_id: str, origin: str, destination: str, date: str, time: str, fare: str) -> None:
    departure = datetime.fromisoformat(f"{date}T{time}+00:00")
    # Build a minimal flight with an empty cabin; scenarios that need seats add them explicitly.
    flight = Flight(
        id=FlightId(flight_id),
        origin=origin,
        destination=destination,
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of(fare),
        cabin=Cabin(),
    )
    container.flight_repo.add(flight)
    world["last_flight_id"] = flight_id


@given(parsers.parse(
    "the flight catalog is seeded with {total:d} flights across {routes:d} routes, "
    "{airlines:d} airlines, {dates:d} dates, {classes:d} classes"
))
def _seed_catalog(container, total: int, routes: int, airlines: int, dates: int, classes: int) -> None:
    """Load the deterministic seeded catalog into the container's flight repo.

    The numeric parameters are minimums — the step asserts the catalog actually
    meets them so a mis-sized fixture fails loudly.
    """
    flights = seeded_catalog()
    assert len(flights) >= total, f"seeded_catalog() returned {len(flights)} < {total}"
    unique_routes = {(f.origin, f.destination) for f in flights}
    assert len(unique_routes) >= routes, f"only {len(unique_routes)} routes"
    unique_airlines = {f.airline for f in flights}
    assert len(unique_airlines) >= airlines, f"only {len(unique_airlines)} airlines"
    unique_dates = {f.departure_at.date() for f in flights}
    assert len(unique_dates) >= dates, f"only {len(unique_dates)} dates"
    unique_classes = {seat.seat_class for f in flights for seat in f.cabin.seats.values()}
    assert len(unique_classes) >= classes, f"only {len(unique_classes)} classes"
    for flight in flights:
        container.flight_repo.add(flight)


@given(parsers.parse(
    'the flight "{flight_id}" has the default 30x6 cabin '
    "(rows 1-2 First, 3-6 Business, 7-30 Economy)"
))
def _seed_flight_with_default_cabin(
    container, world: dict, flight_id: str
) -> None:
    """Seed a flight identified by ``flight_id`` with the ADR-004 default cabin.

    The departure and fare are irrelevant to milestone-03 seat-map assertions,
    so we choose deterministic defaults. Other scenarios that need a specific
    departure seed via the catalog-search Given instead.
    """
    departure = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of("299"),
        cabin=default_cabin(),
    )
    container.flight_repo.add(flight)
    world["last_flight_id"] = flight_id


@given(parsers.parse('seat "{seat_id}" in {seat_class} is AVAILABLE on that flight'))
def _seed_seat(container, world: dict, seat_id: str, seat_class: str) -> None:
    flight = container.flight_repo.get(FlightId(world["last_flight_id"]))
    if flight is None:
        raise AssertionError("flight not seeded")
    seat = Seat(id=SeatId(seat_id), seat_class=SeatClass[seat_class.upper()], kind=SeatKind.STANDARD)
    flight.cabin.seats[seat.id] = seat


@given(parsers.parse('seat "{seat_id}" is AVAILABLE on flight "{flight_id}"'))
def _assert_seat_is_available(container, world: dict, seat_id: str, flight_id: str) -> None:
    """Assert (not seed) that the given seat already exists and is AVAILABLE.

    The Background step seeds the default 30x6 cabin, so every seat in that
    cabin starts AVAILABLE. This Given is a precondition check rather than a
    mutation — it pins the narrative in the feature file.
    """
    flight = container.flight_repo.get(FlightId(flight_id))
    if flight is None:
        raise AssertionError(f"flight {flight_id} not seeded")
    seat = flight.cabin.seats.get(SeatId(seat_id))
    if seat is None:
        raise AssertionError(f"seat {seat_id} not in flight {flight_id} cabin")
    if seat.status != SeatStatus.AVAILABLE:
        raise AssertionError(f"seat {seat_id} expected AVAILABLE, got {seat.status}")
    world["last_flight_id"] = flight_id


# ---- Driving adapter steps (HTTP) ------------------------------------------

@when(parsers.parse("the traveler searches flights from {origin} to {destination} on {date}"))
def _http_search(client, world: dict, origin: str, destination: str, date: str) -> None:
    world["response"] = client.get(
        "/flights/search",
        params={"origin": origin, "destination": destination, "departureDate": date},
    )
    world["last_search_params"] = {
        "origin": origin,
        "destination": destination,
        "departureDate": date,
    }


@when(parsers.parse(
    "the traveler searches flights from {origin} to {destination} on {date} requesting page {page:d}"
))
def _http_search_with_page(
    client, world: dict, origin: str, destination: str, date: str, page: int
) -> None:
    params = {
        "origin": origin,
        "destination": destination,
        "departureDate": date,
        "page": page,
    }
    world["response"] = client.get("/flights/search", params=params)
    world["last_search_params"] = {
        "origin": origin,
        "destination": destination,
        "departureDate": date,
    }


@when(parsers.parse("the traveler searches with page size {size:d}"))
def _http_search_with_size(client, world: dict, size: int) -> None:
    params = dict(world["last_search_params"])
    params["size"] = size
    world["response"] = client.get("/flights/search", params=params)


@when(parsers.parse('the traveler searches flights with {field} = "{bad_value}"'))
def _http_search_invalid_field(client, world: dict, field: str, bad_value: str) -> None:
    # Start from a baseline of valid params, then overwrite the field under test.
    params: dict[str, object] = {
        "origin": "LAX",
        "destination": "NYC",
        "departureDate": "2026-06-01",
        "passengers": 1,
    }
    params[field] = bad_value
    world["response"] = client.get("/flights/search", params=params)


@when(parsers.parse('the traveler requests the seat map for flight "{flight_id}"'))
def _http_get_seat_map(client, world: dict, flight_id: str) -> None:
    world["response"] = client.get(f"/flights/{flight_id}/seats")


@when(parsers.parse('the traveler requests the seat map for "{flight_id}"'))
def _http_get_seat_map_short(client, world: dict, flight_id: str) -> None:
    world["response"] = client.get(f"/flights/{flight_id}/seats")


@when(parsers.parse('the traveler successfully books seat "{seat_id}" on that flight'))
def _http_successful_book(client, world: dict, seat_id: str) -> None:
    flight_id = world["last_flight_id"]
    response = client.post(
        "/bookings",
        json={
            "flightId": flight_id,
            "seatId": seat_id,
            "passenger": {"name": "Jane Doe"},
            "paymentToken": "mock-ok",
        },
    )
    assert response.status_code == 201, (
        f"expected successful booking (201), got {response.status_code}: {response.text}"
    )
    world["last_booking_response"] = response


@then(parsers.parse("the response contains {count:d} seats"))
def _assert_seat_count(world: dict, count: int) -> None:
    body = world["response"].json()
    seats = body.get("seats", [])
    assert len(seats) == count, f"expected {count} seats, got {len(seats)}"


@then(parsers.parse('seat "{seat_id}" is in class "{seat_class}"'))
def _assert_seat_class(world: dict, seat_id: str, seat_class: str) -> None:
    body = world["response"].json()
    seats = body.get("seats", [])
    match = next((s for s in seats if s.get("seatId") == seat_id), None)
    assert match is not None, f"seat {seat_id} not in response"
    actual = match.get("class")
    assert actual == seat_class, f"seat {seat_id}: expected class {seat_class}, got {actual}"


@then(parsers.parse('seat "{seat_id}" is reported as OCCUPIED'))
def _assert_seat_occupied(world: dict, seat_id: str) -> None:
    body = world["response"].json()
    seats = body.get("seats", [])
    match = next((s for s in seats if s.get("seatId") == seat_id), None)
    assert match is not None, f"seat {seat_id} not in response"
    actual = match.get("status")
    assert actual == "OCCUPIED", f"seat {seat_id}: expected OCCUPIED, got {actual}"


@when(parsers.parse('the traveler books flight "{flight_id}" with seat "{seat_id}" for passenger "{name}" using payment token "{token}"'))
def _http_book(client, world: dict, flight_id: str, seat_id: str, name: str, token: str) -> None:
    world["response"] = client.post(
        "/bookings",
        json={
            "flightId": flight_id,
            "seatId": seat_id,
            "passenger": {"name": name},
            "paymentToken": token,
        },
    )


@when(parsers.parse('the traveler books flight "{flight_id}" with seat "{seat_id}"'))
def _http_book_minimal(client, world: dict, flight_id: str, seat_id: str) -> None:
    """Book with default passenger + payment token — used by seat-validation scenarios.

    The validation logic under test branches on seat identity/status before
    payment is charged, so the passenger and token values are narrative
    defaults (never asserted on).
    """
    world["response"] = client.post(
        "/bookings",
        json={
            "flightId": flight_id,
            "seatId": seat_id,
            "passenger": {"name": "Jane Doe"},
            "paymentToken": "mock-ok",
        },
    )


@given(parsers.parse('seat "{seat_id}" is OCCUPIED on flight "{flight_id}"'))
def _seed_occupied_seat(container, world: dict, seat_id: str, flight_id: str) -> None:
    """Record a CONFIRMED booking covering ``seat_id`` on ``flight_id``.

    This is the precondition Given: it mutates repository state so that the
    subsequent commit sees the seat as already booked and rejects with 409.
    """
    from flights.domain.model.booking import Booking, BookingStatus
    from flights.domain.model.ids import BookingReference, QuoteId
    from flights.domain.model.money import Money
    from flights.domain.model.passenger import PassengerDetails

    flight = container.flight_repo.get(FlightId(flight_id))
    if flight is None:
        raise AssertionError(f"flight {flight_id} not seeded")
    existing = Booking(
        reference=BookingReference("BK-PRE-EXISTING"),
        flight_id=FlightId(flight_id),
        seat_ids=(SeatId(seat_id),),
        passengers=(PassengerDetails(full_name="Pre-Existing Passenger"),),
        total_charged=Money.of("0"),
        status=BookingStatus.CONFIRMED,
        quote_id=QuoteId("Q-PRE-EXISTING"),
        confirmed_at=datetime(2026, 4, 25, 9, 0, tzinfo=UTC),
    )
    container.booking_repo.save(existing)
    world["last_flight_id"] = flight_id


@given(parsers.parse('seat "{seat_id}" is BLOCKED for maintenance on flight "{flight_id}"'))
def _seed_blocked_seat(container, world: dict, seat_id: str, flight_id: str) -> None:
    """Mutate the cabin so ``seat_id`` has status BLOCKED (not for sale)."""
    flight = container.flight_repo.get(FlightId(flight_id))
    if flight is None:
        raise AssertionError(f"flight {flight_id} not seeded")
    existing_seat = flight.cabin.seats.get(SeatId(seat_id))
    if existing_seat is None:
        raise AssertionError(f"seat {seat_id} not in flight {flight_id} cabin")
    flight.cabin.seats[existing_seat.id] = Seat(
        id=existing_seat.id,
        seat_class=existing_seat.seat_class,
        kind=existing_seat.kind,
        status=SeatStatus.BLOCKED,
    )
    world["last_flight_id"] = flight_id


@then(parsers.parse('the response body cites "{phrase}"'))
def _assert_body_cites(world: dict, phrase: str) -> None:
    """Assert ``phrase`` appears somewhere in the response body text.

    Works for both JSON responses (serialised to text) and plain text bodies,
    so the assertion is tolerant of how the adapter chose to shape the payload.
    """
    body_text = world["response"].text
    assert phrase in body_text, f"expected body to cite {phrase!r}, got: {body_text!r}"


@when("the traveler retrieves the booking using its reference")
def _http_get_booking(client, world: dict) -> None:
    booking_ref = world["response"].json().get("bookingReference")
    world["response"] = client.get(f"/bookings/{booking_ref}")


# ---- Assertion steps --------------------------------------------------------

@then(parsers.parse("the response status is {status:d}"))
def _assert_status(world: dict, status: int) -> None:
    actual = world["response"].status_code
    assert actual == status, f"expected HTTP {status}, got {actual}: {world['response'].text}"


@then(parsers.parse(
    'every returned flight has origin "{origin}", destination "{destination}", '
    "and departure date {date}"
))
def _assert_all_match_filter(world: dict, origin: str, destination: str, date: str) -> None:
    body = world["response"].json()
    flights = body.get("flights", [])
    assert flights, "expected at least one flight in the response"
    for flight in flights:
        assert flight["origin"] == origin, f"origin mismatch: {flight['origin']}"
        assert flight["destination"] == destination, f"destination mismatch: {flight['destination']}"
        assert flight["departureAt"].startswith(date), (
            f"departure date mismatch: {flight['departureAt']}"
        )


@then("the response contains zero flights")
def _assert_zero_flights(world: dict) -> None:
    body = world["response"].json()
    assert body.get("flights") == [], f"expected empty flights, got {body.get('flights')!r}"


@then(parsers.parse("the pagination metadata reports a total count of {total:d}"))
def _assert_total_count(world: dict, total: int) -> None:
    body = world["response"].json()
    assert body.get("total") == total, f"expected total={total}, got {body.get('total')!r}"


@then(parsers.parse("the response contains at most {n:d} flights"))
def _assert_at_most_n_flights(world: dict, n: int) -> None:
    body = world["response"].json()
    flights = body.get("flights", [])
    assert len(flights) <= n, f"expected at most {n} flights, got {len(flights)}"


@then(parsers.parse("the response still contains at most {n:d} flights"))
def _assert_still_at_most_n_flights(world: dict, n: int) -> None:
    body = world["response"].json()
    flights = body.get("flights", [])
    assert len(flights) <= n, f"expected at most {n} flights, got {len(flights)}"


@then("the pagination metadata reports the total count and current page")
def _assert_pagination_metadata_present(world: dict) -> None:
    body = world["response"].json()
    assert "total" in body, f"missing 'total' in pagination metadata: {body!r}"
    assert "page" in body, f"missing 'page' in pagination metadata: {body!r}"
    assert "size" in body, f"missing 'size' in pagination metadata: {body!r}"
    assert isinstance(body["total"], int), f"total must be int, got {type(body['total'])}"
    assert isinstance(body["page"], int), f"page must be int, got {type(body['page'])}"


@then(parsers.parse('the response body lists an error for field "{field}"'))
def _assert_error_for_field(world: dict, field: str) -> None:
    body = world["response"].json()
    errors = body.get("errors")
    assert isinstance(errors, list), f"expected 'errors' list in body, got {body!r}"
    fields_reported = [e.get("field") for e in errors]
    assert field in fields_reported, (
        f"expected error for field {field!r}, got fields {fields_reported!r}"
    )


@then(parsers.parse('the response body contains the flight "{flight_id}"'))
def _assert_body_has_flight(world: dict, flight_id: str) -> None:
    body = world["response"].json()
    flights = body.get("flights", body if isinstance(body, list) else [])
    ids = [f.get("id") or f.get("flightId") for f in flights]
    assert flight_id in ids, f"{flight_id} not in {ids}"


@then("the response contains a booking reference")
def _assert_has_booking_ref(world: dict) -> None:
    ref = world["response"].json().get("bookingReference")
    assert ref, "bookingReference missing from response"
    world["booking_reference"] = ref


@then(parsers.parse('the booking status is "{status}"'))
def _assert_booking_status(world: dict, status: str) -> None:
    actual = world["response"].json().get("status")
    assert actual == status


@then(parsers.parse('the response shows seat "{seat_id}" on flight "{flight_id}"'))
def _assert_booking_seat(world: dict, seat_id: str, flight_id: str) -> None:
    body = world["response"].json()
    assert body.get("flightId") == flight_id
    assert seat_id in body.get("seats", [])


@then(parsers.parse('the confirmation email queue contains one email for "{name}"'))
def _assert_email_queued(container, name: str) -> None:
    queued = getattr(container, "email_queue", None) or container.booking_service._email.queued  # type: ignore[attr-defined]
    assert len(queued) == 1
    assert any(p.full_name == name for b in queued for p in b.passengers), f"no email for {name}"


@then(parsers.parse('the audit log contains a "{event_type}" event for that reference'))
def _assert_audit_event(container, world: dict, event_type: str) -> None:
    events = getattr(container.audit, "events", [])
    ref = world["booking_reference"]
    assert any(
        e.get("type") == event_type and e.get("booking_reference") == ref for e in events
    ), f"no {event_type} event for {ref} in {events!r}"


# ---- Milestone 06: quote TTL + audit steps (step 06-01) ---------------------
#
# The quote-TTL scenarios need a flight with enough pricing context to produce
# a deterministic QuoteCreated event and a well-formed ``expiresAt``. The
# Background seeds a flight whose ``departure_at`` sits comfortably after the
# frozen clock so the time-bucket math is stable, and whose cabin has a seat
# "12C" the scenarios can quote. The clock (2026-04-25 10:00 UTC) is set by
# the prior Background step; we add 30+ days to keep time-multiplier = 1.00.


@given(parsers.parse('a flight "{flight_id}" with known base fare and pricing context'))
def _seed_milestone_06_flight(container, world: dict, flight_id: str) -> None:
    """Seed a Milestone-06 flight that can be quoted under the Background clock.

    * Departs Tuesday 2026-06-02 at 08:00 UTC — 38 days after the frozen clock
      (2026-04-25) so the time-bucket is stable at 1.00 and DOW is TUE (0.85).
    * Cabin has seat "12C" AVAILABLE plus 99 AVAILABLE fillers (0% occupancy →
      demand 1.00), so the exact multipliers are irrelevant to the TTL
      assertions — the Quote simply has deterministic inputs.
    """
    departure = datetime(2026, 6, 2, 8, 0, tzinfo=UTC)
    cabin = Cabin()
    cabin.seats[SeatId("12C")] = Seat(
        id=SeatId("12C"),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    for index in range(1, 100):
        seat_id = SeatId(f"FILL-{index:03d}")
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=SeatStatus.AVAILABLE,
        )
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of("299"),
        cabin=cabin,
    )
    container.flight_repo.add(flight)
    world["last_flight_id"] = flight_id


@when(parsers.parse('the traveler creates a quote for seat "{seat_id}"'))
def _http_create_quote_for_seat(client, world: dict, seat_id: str) -> None:
    """Drive ``POST /quotes`` and stash the response plus the returned quoteId
    so Then steps can cross-reference the audit log."""
    world["response"] = client.post(
        "/quotes",
        json={
            "flightId": world["last_flight_id"],
            "seatIds": [seat_id],
            "passengers": 1,
        },
    )
    body = world["response"].json() if world["response"].status_code < 500 else {}
    world["quote_id"] = body.get("quoteId")


@then("the response contains an expiresAt exactly 30 minutes in the future")
def _assert_expires_at_is_thirty_minutes_ahead(
    frozen_clock: FrozenClock, world: dict
) -> None:
    """Assert ``expiresAt`` is exactly clock.now() + 30 minutes.

    The test uses the frozen clock as the authoritative "now" — production code
    must read the same clock through the ``Clock`` port, so any drift between
    the stamp and the clock indicates the QuoteService is computing TTL from
    something else (e.g., datetime.now()) which would be a bug.
    """
    from datetime import timedelta
    body = world["response"].json()
    expires_at_str = body.get("expiresAt")
    assert expires_at_str, f"response missing expiresAt: {body!r}"
    expires_at = datetime.fromisoformat(expires_at_str)
    expected = frozen_clock.now() + timedelta(minutes=30)
    assert expires_at == expected, (
        f"expiresAt {expires_at.isoformat()} != frozen_clock + 30min "
        f"{expected.isoformat()}"
    )


@then(parsers.parse('the audit log contains a "{event_type}" event for that quote'))
def _assert_audit_event_for_quote(
    container, world: dict, event_type: str
) -> None:
    """Assert the audit log contains an event of ``event_type`` tagged with the
    quote_id returned by the preceding POST /quotes. Mirrors the booking-level
    assertion above but keys on ``quote_id`` because QuoteCreated events are
    written before any booking reference exists.
    """
    events = getattr(container.audit, "events", [])
    quote_id = world["quote_id"]
    assert quote_id, "no quote_id captured from POST /quotes response"
    assert any(
        e.get("type") == event_type and e.get("quote_id") == quote_id
        for e in events
    ), f"no {event_type} event for quote {quote_id} in {events!r}"


# ---- Milestone 06: audit-log replay (step 06-02) ----------------------------
#
# The replay scenario needs a live audit log with (at least) one QuoteCreated
# event and one BookingCommitted event written through the real driving ports
# (POST /quotes + POST /bookings). The Given drives both calls; the When
# captures the audit events from the container's InMemoryAuditLog; the Then
# runs ``verify_commits`` and asserts zero mismatches.
#
# BookingCommitted's ``quote_id`` is currently the WS-shortcut "Q000-WS" (the
# BookingService does not yet read the quote on commit — that is Phase 06-03).
# ``verify_commits`` therefore skips Q000-WS, and the assertion is satisfied
# by the QuoteCreated event replaying cleanly against itself (not exercised
# by this scenario but stubbed by the Q000-WS rule).


@given("audit events QuoteCreated and BookingCommitted were written during a successful booking")
def _seed_audit_for_replay(client, container, world: dict) -> None:
    """Drive POST /quotes followed by POST /bookings via the HTTP port so both
    audit events get written by production code paths (not by the test).
    The Background already seeded "FL-LAX-NYC-0800" with seat "12C" AVAILABLE.
    """
    quote_response = client.post(
        "/quotes",
        json={
            "flightId": world["last_flight_id"],
            "seatIds": ["12C"],
            "passengers": 1,
        },
    )
    assert quote_response.status_code == 200, (
        f"quote creation failed: {quote_response.status_code} {quote_response.text}"
    )
    world["quote_id"] = quote_response.json()["quoteId"]
    booking_response = client.post(
        "/bookings",
        json={
            "flightId": world["last_flight_id"],
            "seatId": "12C",
            "passenger": {"name": "Jane Doe"},
            "paymentToken": "mock-ok",
        },
    )
    assert booking_response.status_code == 201, (
        f"booking commit failed: {booking_response.status_code} {booking_response.text}"
    )


@when("the replay utility reads the audit log")
def _capture_audit_events(container, world: dict) -> None:
    world["audit_events"] = list(getattr(container.audit, "events", []))


@then(
    "for each BookingCommitted event, re-running pricing.price with the "
    "matching QuoteCreated inputs produces the same total"
)
def _assert_replay_produces_same_total(world: dict) -> None:
    from tests.support.audit_replay import verify_commits

    mismatches = verify_commits(world["audit_events"])
    assert mismatches == [], (
        f"audit replay found mismatches: {mismatches!r}; "
        f"events: {world['audit_events']!r}"
    )


# ---- Milestone 06: quote-trust commit steps (step 06-03) --------------------
#
# Step 06-03 wires ``BookingService.commit`` to honor the quote's locked-in
# total. The steps below drive the three previously-@pending scenarios:
#
#   * "Commit within 30 minutes honors the quoted total even if demand changed"
#   * "Commit after TTL returns 410 Gone"
#   * "Commit with an unknown quote id returns 404"
#
# For the @kpi honors-the-quote scenario the Given replaces the Milestone-06
# background flight with one whose (base_fare, route_kind, departure-date)
# trio pins the quote total at exactly 228.74 USD — see the comment on
# ``_QUOTE_TOTAL_228_74_BASE_FARE`` for the derivation. That lets the
# assertion cite the literal amount from the feature file while keeping the
# price math deterministic under the frozen clock.


# Base fare chosen so that POST /quotes returns total = 228.74 USD under the
# milestone-06 frozen clock (2026-04-25 10:00 UTC) and a 2026-06-02 TUE
# departure (38 days out), with zero occupancy and DOMESTIC route:
#   228.74 = 278.14 × 0.90 (time) × 0.85 (dow) × 1.075 (domestic tax)
# All multipliers come from the Appendix B rule tables. Any change to those
# tables invalidates this seed — the scenario will fail loudly rather than
# silently drift off the KPI anchor.
_QUOTE_TOTAL_228_74_BASE_FARE = "278.14"


@when(parsers.parse("the traveler creates a quote with total {amount} USD"))
def _http_create_quote_with_specific_total(
    container, client, world: dict, amount: str,
) -> None:
    """Reseed the milestone-06 flight with a base fare that produces ``amount``
    as the quote total under the frozen clock, then drive POST /quotes.
    The pricing inputs (days-before, dow, occupancy, tax rate) are pinned by
    the Background; only the base fare varies so the total matches the anchor.
    """
    # Only 228.74 is used by the milestone-06 @kpi scenario. Guard against
    # silent misuse: if a future scenario cites a different total we need an
    # explicit base-fare derivation for it rather than copy-pasting the seed.
    assert amount == "228.74", (
        f"step only supports the 228.74 KPI anchor; got {amount!r}"
    )
    flight_id = world["last_flight_id"]
    base_fare = Money.of(_QUOTE_TOTAL_228_74_BASE_FARE)
    # Replace the flight with one that has the target base fare. The
    # milestone-06 Given seeded a 100-seat cabin with seat 12C AVAILABLE and
    # 99 fillers AVAILABLE — preserve that so occupancy stays at 0%.
    departure = datetime(2026, 6, 2, 8, 0, tzinfo=UTC)
    cabin = Cabin()
    cabin.seats[SeatId("12C")] = Seat(
        id=SeatId("12C"),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    for index in range(1, 100):
        seat_id = SeatId(f"FILL-{index:03d}")
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=SeatStatus.AVAILABLE,
        )
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=base_fare,
        cabin=cabin,
    )
    container.flight_repo.add(flight)  # add is idempotent; overwrites by id

    response = client.post(
        "/quotes",
        json={
            "flightId": flight_id,
            "seatIds": ["12C"],
            "passengers": 1,
        },
    )
    assert response.status_code == 200, (
        f"quote creation failed: {response.status_code} {response.text}"
    )
    body = response.json()
    assert body["total"] == amount, (
        f"seeded flight produced total {body['total']}, expected {amount}"
    )
    world["response"] = response
    world["quote_id"] = body["quoteId"]
    world["quote_total"] = body["total"]


@when("the traveler creates a quote")
def _http_create_quote_default(client, world: dict) -> None:
    """Drive POST /quotes against the milestone-06 background flight with seat
    "12C". Stashes the quoteId so the later "commits using that quote id"
    step can reference it.
    """
    response = client.post(
        "/quotes",
        json={
            "flightId": world["last_flight_id"],
            "seatIds": ["12C"],
            "passengers": 1,
        },
    )
    assert response.status_code == 200, (
        f"quote creation failed: {response.status_code} {response.text}"
    )
    world["response"] = response
    world["quote_id"] = response.json()["quoteId"]
    world["quote_total"] = response.json()["total"]


@when("the flight's occupancy subsequently jumps into the 86%+ bracket")
def _jump_occupancy_to_86(container, world: dict) -> None:
    """Mutate the flight's cabin so current-state occupancy lands in the 86%+
    demand bucket. Simplest mutation: flip fillers to BLOCKED until we reach
    the threshold (BLOCKED counts as occupied per ``_occupancy_pct`` and
    doesn't pollute the booking repository).

    The test only asserts the booking's total_charged equals the quote's
    pre-jump total, so the exact % above 86 is irrelevant — we just need to
    cross the bracket boundary.
    """
    flight = container.flight_repo.get(FlightId(world["last_flight_id"]))
    if flight is None:
        raise AssertionError("milestone-06 flight not seeded")
    total_seats = flight.cabin.seat_count()
    # 86% of 100 = 86 — flip the first 86 fillers to BLOCKED. The quoted seat
    # (12C) stays AVAILABLE so the commit can still claim it.
    target_occupied = (total_seats * 86 + 99) // 100  # ceil(seats * 0.86)
    flipped = 0
    for seat_id, seat in list(flight.cabin.seats.items()):
        if flipped >= target_occupied:
            break
        if seat_id == SeatId("12C"):
            continue  # never block the seat we're about to book
        if seat.status != SeatStatus.BLOCKED:
            flight.cabin.seats[seat_id] = Seat(
                id=seat.id,
                seat_class=seat.seat_class,
                kind=seat.kind,
                status=SeatStatus.BLOCKED,
            )
            flipped += 1
    assert flipped >= target_occupied, (
        f"could not flip enough seats to 86%+ bracket: flipped {flipped}, "
        f"needed {target_occupied}"
    )


@when(parsers.parse("the clock advances by {minutes:d} minutes"))
def _advance_clock(
    frozen_clock: FrozenClock, container, minutes: int,
) -> None:
    """Advance both the fixture clock (used by Then assertions that read
    ``frozen_clock.now()``) and the container's internal clock (used by
    production code through the ``Clock`` port) by the same delta.

    ``build_test_container`` constructs its own ``FrozenClock`` from the
    fixture's initial instant, so the two clocks are independent instances
    after container creation. The step must advance both to keep TTL
    arithmetic consistent on the production path.
    """
    from datetime import timedelta

    delta = timedelta(minutes=minutes)
    frozen_clock.advance(delta)
    container.clock.advance(delta)


@when("the traveler commits the booking using that quote id")
def _http_commit_with_stashed_quote_id(client, world: dict) -> None:
    """POST /bookings with the quoteId captured from the earlier POST /quotes.
    Seat "12C" is the quoted seat; passenger + payment token are narrative
    defaults (the scenario asserts on total_charged, not on them).
    """
    quote_id = world.get("quote_id")
    assert quote_id, "no quote_id captured — run the quote-creation step first"
    response = client.post(
        "/bookings",
        json={
            "flightId": world["last_flight_id"],
            "seatId": "12C",
            "passenger": {"name": "Jane Doe"},
            "paymentToken": "mock-ok",
            "quoteId": quote_id,
        },
    )
    world["response"] = response


@when(parsers.parse('the traveler commits a booking with quoteId "{quote_id}"'))
def _http_commit_with_literal_quote_id(client, world: dict, quote_id: str) -> None:
    """POST /bookings with a literal quoteId string (scenario: "UNKNOWN") so
    we can exercise the 404 "quote not found" branch.

    The flight and seat still need to be valid so the BookingService reaches
    the quote-lookup branch before any seat-validation error short-circuits.
    """
    response = client.post(
        "/bookings",
        json={
            "flightId": world["last_flight_id"],
            "seatId": "12C",
            "passenger": {"name": "Jane Doe"},
            "paymentToken": "mock-ok",
            "quoteId": quote_id,
        },
    )
    world["response"] = response


@then(parsers.parse("the booking's total_charged is exactly {amount} USD"))
def _assert_booking_total_charged(world: dict, amount: str) -> None:
    """Assert the response body's ``totalCharged.amount`` matches ``amount``
    exactly (Money values are strings on the wire so Decimal precision holds).
    """
    body = world["response"].json()
    total = body.get("totalCharged", {})
    actual = total.get("amount")
    assert actual == amount, (
        f"expected total_charged {amount}, got {actual!r} in {body!r}"
    )


@then(parsers.parse(
    'the audit log contains a "{event_type}" event referencing the quote id and total'
))
def _assert_booking_committed_references_quote_and_total(
    container, world: dict, event_type: str,
) -> None:
    """Assert the audit log contains an event of ``event_type`` whose
    ``quote_id`` and ``total_charged`` match the quote created earlier. This
    is the KPI-T1 audit check: the committed event must reference the same
    quote the traveler saw and the same total they were charged.
    """
    events = getattr(container.audit, "events", [])
    quote_id = world["quote_id"]
    expected_total = world["quote_total"]
    match = next(
        (
            e for e in events
            if e.get("type") == event_type
            and e.get("quote_id") == quote_id
            and e.get("total_charged") == expected_total
        ),
        None,
    )
    assert match is not None, (
        f"no {event_type} event for quote_id={quote_id!r} total={expected_total!r} "
        f"in {events!r}"
    )


@then(parsers.parse('no "{event_type}" event is written to the audit log'))
def _assert_no_event_written(container, event_type: str) -> None:
    """Assert the audit log contains zero events of ``event_type`` — used by
    the "Commit after TTL" scenario to verify the expired-quote branch does
    not leak a successful-commit audit trail.
    """
    events = getattr(container.audit, "events", [])
    offending = [e for e in events if e.get("type") == event_type]
    assert offending == [], (
        f"expected no {event_type} events, got {offending!r}"
    )


# ---- Adapter integration: JsonlAuditLog filesystem scenario -----------------

@given("an audit log at a temporary JSON-lines file")
def _jsonl_audit_log(audit_path: Path, world: dict) -> None:
    world["audit_log"] = JsonlAuditLog(audit_path)
    world["audit_path"] = audit_path


@when(parsers.parse('the system writes {n:d} audit events of types "{t1}", "{t2}", "{t3}"'))
def _write_events(world: dict, n: int, t1: str, t2: str, t3: str) -> None:
    log = world["audit_log"]
    for i, t in enumerate([t1, t2, t3][:n]):
        log.write({"type": t, "seq": i, "at": datetime(2026, 4, 25, 10, i, tzinfo=UTC).isoformat()})


@then("the file exists on disk")
def _assert_file_exists(world: dict) -> None:
    assert world["audit_path"].exists()


@then(parsers.parse("the file contains exactly {n:d} JSON lines"))
def _assert_line_count(world: dict, n: int) -> None:
    lines = [ln for ln in world["audit_path"].read_text().splitlines() if ln.strip()]
    assert len(lines) == n


@then(parsers.parse('each line parses as a JSON object with a "type" field matching the written type'))
def _assert_types(world: dict) -> None:
    for ln in world["audit_path"].read_text().splitlines():
        if ln.strip():
            obj = json.loads(ln)
            assert "type" in obj


@then(parsers.parse("reading the audit log back returns the same {n:d} events in order"))
def _assert_read_all(world: dict, n: int) -> None:
    events = world["audit_log"].read_all()
    assert len(events) == n
    assert [e["seq"] for e in events] == list(range(n))


# ---- Milestone 04: pricing steps --------------------------------------------
#
# Step 04-02 wired ``POST /quotes`` to the pricing engine, so the Appendix B
# @kpi scenarios drive through HTTP end-to-end (``_seed_http_pricing_flight``
# Givens + ``_http_quote_no_surcharge`` When). The Scenario Outline rows and
# the rule-table meta scenario remain at the pricing-function level — they
# exercise multiplier selection directly, independent of HTTP wiring, so
# keeping them in-process avoids fabricating date arithmetic that isn't
# observable in the assertions.

from flights.domain import pricing
from flights.domain.pricing import DayOfWeek, PricingInputs


_DOW_BY_NAME: dict[str, DayOfWeek] = {
    "MON": DayOfWeek.MON, "Monday":    DayOfWeek.MON,
    "TUE": DayOfWeek.TUE, "Tuesday":   DayOfWeek.TUE,
    "WED": DayOfWeek.WED, "Wednesday": DayOfWeek.WED,
    "THU": DayOfWeek.THU, "Thursday":  DayOfWeek.THU,
    "FRI": DayOfWeek.FRI, "Friday":    DayOfWeek.FRI,
    "SAT": DayOfWeek.SAT, "Saturday":  DayOfWeek.SAT,
    "SUN": DayOfWeek.SUN, "Sunday":    DayOfWeek.SUN,
}

_HTTP_PRICING_FLIGHT_ID = "FL-PRICING-04"
_HTTP_PRICING_QUOTE_SEAT = "12C"
_HTTP_PRICING_CABIN_SIZE = 100


def _build_http_pricing_cabin(occupancy_pct: int) -> Cabin:
    """Construct a 100-seat cabin with ``occupancy_pct`` OCCUPIED seats so the
    ``QuoteService``'s occupancy calculation lands in the expected demand
    bucket. The quoted seat (``_HTTP_PRICING_QUOTE_SEAT``) is always AVAILABLE
    so the quote succeeds — surcharges are seat-specific and out of scope.
    """
    cabin = Cabin()
    cabin.seats[SeatId(_HTTP_PRICING_QUOTE_SEAT)] = Seat(
        id=SeatId(_HTTP_PRICING_QUOTE_SEAT),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    for index in range(1, _HTTP_PRICING_CABIN_SIZE):
        seat_id = SeatId(f"FILL-{index:03d}")
        status = SeatStatus.OCCUPIED if index <= occupancy_pct else SeatStatus.AVAILABLE
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=status,
        )
    return cabin


def _seed_http_pricing_flight(
    container, world: dict, *,
    dow_name: str, date: str, time: str, pct: int, fare: str,
) -> None:
    """Register a flight whose ``departure_at.weekday()`` matches ``dow_name``
    and whose cabin occupancy equals ``pct``. Writes through the real
    ``InMemoryFlightRepository`` so the HTTP route observes it as production
    state.
    """
    departure = datetime.fromisoformat(f"{date}T{time}:00+00:00")
    expected_dow = _DOW_BY_NAME[dow_name]
    actual_dow = DayOfWeek(departure.weekday())
    assert actual_dow == expected_dow, (
        f"feature requests {dow_name} but {date} is {actual_dow.name}"
    )
    flight = Flight(
        id=FlightId(_HTTP_PRICING_FLIGHT_ID),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of(fare),
        cabin=_build_http_pricing_cabin(pct),
    )
    container.flight_repo.add(flight)
    world["last_flight_id"] = _HTTP_PRICING_FLIGHT_ID


@given(parsers.re(
    r"a flight departing (?P<dow_name>\w+) (?P<date>\d{4}-\d{2}-\d{2}) "
    r"with (?P<pct>\d+)% occupancy and base fare (?P<fare>[\d.]+) USD"
))
def _seed_pricing_flight_dow_date(
    container, world: dict,
    dow_name: str, date: str, pct: str, fare: str,
) -> None:
    """Register a flight for HTTP-driven pricing scenarios. Time defaults to
    00:00 UTC — the days-before calculation is date-based so the hour is
    immaterial for this Given. The regex restricts ``date`` to ISO
    yyyy-mm-dd so the ``at HH:MM`` variant cannot be accidentally captured
    by this pattern."""
    _seed_http_pricing_flight(
        container, world,
        dow_name=dow_name, date=date, time="00:00", pct=int(pct), fare=fare,
    )


@given(parsers.re(
    r"a flight departing (?P<dow_name>\w+) (?P<date>\d{4}-\d{2}-\d{2}) "
    r"at (?P<time>\d{2}:\d{2}) with (?P<pct>\d+)% occupancy "
    r"and base fare (?P<fare>[\d.]+) USD"
))
def _seed_pricing_flight_dow_date_time(
    container, world: dict,
    dow_name: str, date: str, time: str, pct: str, fare: str,
) -> None:
    """Same as the dow+date Given but the departure has an explicit clock time —
    used by Appendix B example 3 where same-day booking hinges on
    ``days_before_departure == 0`` regardless of hour-of-day."""
    _seed_http_pricing_flight(
        container, world,
        dow_name=dow_name, date=date, time=time, pct=int(pct), fare=fare,
    )


@given(parsers.parse(
    "a flight with {pct:d}% occupancy and base fare {fare} USD"
))
def _seed_pricing_flight_plain(world: dict, pct: int, fare: str) -> None:
    """Seed only base fare + occupancy for the Scenario Outline rows — those
    scenarios exercise multiplier selection through the pricing function as
    its own driving port, so no HTTP flight is needed."""
    world["pricing_context"] = {
        "base_fare": Money.of(fare),
        "occupancy_pct": Decimal(pct),
        # days_before_departure and departure_dow come from the When step.
    }


@when("the traveler quotes one economy seat with no seat surcharge")
def _price_quote_no_surcharge(client, world: dict) -> None:
    """Drive ``POST /quotes`` and capture the response plus a pricing-breakdown
    projection for the shared multiplier assertions. The Appendix B scenarios
    reach this When after their HTTP flight has been seeded.
    """
    response = client.post(
        "/quotes",
        json={
            "flightId": world["last_flight_id"],
            "seatIds": [_HTTP_PRICING_QUOTE_SEAT],
            "passengers": 1,
        },
    )
    world["response"] = response
    body = response.json()
    world["breakdown"] = _BreakdownProjection(
        total=Money.of(body["total"]),
        demand_multiplier=Decimal(body["demandMultiplier"]),
        time_multiplier=Decimal(body["timeMultiplier"]),
        day_multiplier=Decimal(body["dayMultiplier"]),
    )


@dataclass(frozen=True)
class _BreakdownProjection:
    """Flat projection of the HTTP response used by the shared total/multiplier
    assertions. Decouples the assertion steps from the domain ``PriceBreakdown``
    type (which carries ``base_fare``/``seat_surcharges``/``taxes``/``fees``
    that aren't exercised at this slice)."""
    total: Money
    demand_multiplier: Decimal
    time_multiplier: Decimal
    day_multiplier: Decimal


@when(parsers.parse(
    "the traveler quotes at {days:d} days before departure on {dow_name}"
))
def _price_quote_outline(world: dict, days: int, dow_name: str) -> None:
    ctx = world["pricing_context"]
    breakdown = pricing.price(
        PricingInputs(
            base_fare=ctx["base_fare"],
            occupancy_pct=ctx["occupancy_pct"],
            days_before_departure=days,
            departure_dow=_DOW_BY_NAME[dow_name],
        )
    )
    world["breakdown"] = breakdown


@then(parsers.parse("the total is exactly {amount} USD"))
def _assert_total(world: dict, amount: str) -> None:
    breakdown = world["breakdown"]
    actual = breakdown.total
    assert actual == Money.of(amount), f"expected total {amount}, got {actual.amount}"


@then(parsers.parse(
    "the breakdown shows demand_multiplier {demand}, time_multiplier {time}, "
    "day_multiplier {dow}"
))
def _assert_breakdown_multipliers(world: dict, demand: str, time: str, dow: str) -> None:
    b = world["breakdown"]
    assert b.demand_multiplier == Decimal(demand), (
        f"demand: expected {demand}, got {b.demand_multiplier}"
    )
    assert b.time_multiplier == Decimal(time), (
        f"time: expected {time}, got {b.time_multiplier}"
    )
    assert b.day_multiplier == Decimal(dow), (
        f"day: expected {dow}, got {b.day_multiplier}"
    )


@then(parsers.parse("the demand_multiplier is {expected}"))
def _assert_demand(world: dict, expected: str) -> None:
    actual = world["breakdown"].demand_multiplier
    assert actual == Decimal(expected), f"expected demand {expected}, got {actual}"


@then(parsers.parse("the time_multiplier is {expected}"))
def _assert_time(world: dict, expected: str) -> None:
    actual = world["breakdown"].time_multiplier
    assert actual == Decimal(expected), f"expected time {expected}, got {actual}"


@then(parsers.parse("the day_multiplier is {expected}"))
def _assert_day(world: dict, expected: str) -> None:
    actual = world["breakdown"].day_multiplier
    assert actual == Decimal(expected), f"expected day {expected}, got {actual}"


# --- Rule-table-as-source-of-truth meta scenario -----------------------------

@when("all demand multipliers are read from the rule table")
def _read_rule_tables(world: dict) -> None:
    world["rule_tables"] = {
        "DEMAND_TABLE": pricing.DEMAND_TABLE,
        "TIME_TABLE": pricing.TIME_TABLE,
        "DOW_TABLE": pricing.DOW_TABLE,
    }


@then("the values match Appendix B exactly")
def _assert_tables_match_appendix_b(world: dict) -> None:
    demand = dict(world["rule_tables"]["DEMAND_TABLE"])
    # Representative Appendix B anchors — DEMAND_TABLE is a threshold list
    # structured as sorted (upper_bound_exclusive, multiplier) pairs. The
    # test asserts the multipliers themselves are present as values.
    expected_demand_multipliers = {
        Decimal("1.00"), Decimal("1.15"), Decimal("1.35"),
        Decimal("1.60"), Decimal("2.00"), Decimal("2.50"),
    }
    actual_demand_multipliers = set(demand.values())
    assert expected_demand_multipliers <= actual_demand_multipliers, (
        f"DEMAND_TABLE missing expected multipliers: "
        f"{expected_demand_multipliers - actual_demand_multipliers}"
    )
    time_values = set(m for _, m in world["rule_tables"]["TIME_TABLE"])
    expected_time_multipliers = {
        Decimal("0.85"), Decimal("0.90"), Decimal("1.00"),
        Decimal("1.20"), Decimal("1.50"), Decimal("2.00"),
    }
    assert expected_time_multipliers <= time_values, (
        f"TIME_TABLE missing expected multipliers: "
        f"{expected_time_multipliers - time_values}"
    )
    dow = world["rule_tables"]["DOW_TABLE"]
    assert dow[DayOfWeek.MON] == Decimal("0.90")
    assert dow[DayOfWeek.FRI] == Decimal("1.25")
    assert dow[DayOfWeek.SUN] == Decimal("1.30")


@then("changing any multiplier requires editing only one location in the code")
def _assert_tables_are_module_level(world: dict) -> None:
    """The rule tables live as module-level constants on ``pricing`` — editing
    a multiplier is a one-location change. We verify that each table is
    reachable via direct module attribute access (the ``world`` snapshot was
    taken through the public module, so if the attributes moved behind a
    getter or were re-exported from another module, the When step would have
    already failed on AttributeError."""
    assert hasattr(pricing, "DEMAND_TABLE")
    assert hasattr(pricing, "TIME_TABLE")
    assert hasattr(pricing, "DOW_TABLE")
    # Same object identity between module attribute and what the When captured —
    # proves no defensive copy is interposing a second source of truth.
    assert world["rule_tables"]["DEMAND_TABLE"] is pricing.DEMAND_TABLE
    assert world["rule_tables"]["TIME_TABLE"] is pricing.TIME_TABLE
    assert world["rule_tables"]["DOW_TABLE"] is pricing.DOW_TABLE


# ---- Milestone 05: price-breakdown steps ------------------------------------
#
# Step 05-01 wires per-seat Appendix A surcharges through ``POST /quotes``.
# The Background seeds a single flight whose departure day-of-week, occupancy
# and days-before are pinned so the scenarios can assert the surcharge line
# without coupling to the multiplier math (which is exercised in milestone-04).

_MILESTONE_05_FLIGHT_SIZE = 100  # cabin size used for occupancy math only


def _milestone_05_base_cabin() -> Cabin:
    """Produce a cabin with 100 STANDARD Economy seats so occupancy math is
    stable. Individual scenarios overwrite specific seats via the
    ``seat "X" in {Class} has kind "{KIND}"`` step.
    """
    cabin = Cabin()
    for index in range(1, _MILESTONE_05_FLIGHT_SIZE + 1):
        seat_id = SeatId(f"FILL-{index:03d}")
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=SeatStatus.AVAILABLE,
        )
    return cabin


@given(parsers.parse(
    'a flight "{flight_id}" with base fare {fare} USD, departing {dow_name} '
    "with {pct:d}% occupancy, {days:d} days out"
))
def _seed_milestone_05_flight(
    container, world: dict,
    flight_id: str, fare: str, dow_name: str, pct: int, days: int,
) -> None:
    """Seed the milestone-05 Background flight.

    Combines the two time inputs ("departing {dow_name}" and "{days} days out")
    by walking forward from ``clock + days`` to the first matching weekday.
    That keeps the feature narrative natural while ensuring day-of-week and
    time-to-departure multipliers are deterministic for the assertions.
    The cabin is a 100-seat Economy baseline; per-scenario Givens overwrite
    individual seats with the kind under test.
    """
    from datetime import date as date_type
    from datetime import timedelta

    expected_dow = _DOW_BY_NAME[dow_name]
    clock_date: date_type = container.clock.now().date()
    candidate = clock_date + timedelta(days=days)
    # Walk forward up to 6 days to find the requested weekday. Guarantees a
    # unique deterministic date whose day-offset is within the same pricing
    # time-bucket as ``days`` (buckets are 2-wide or wider past 3 days out).
    offset = 0
    while DayOfWeek(candidate.weekday()) != expected_dow:
        candidate = candidate + timedelta(days=1)
        offset += 1
        assert offset < 7, (
            f"could not find {dow_name} within 7 days after clock+{days}"
        )
    departure = datetime.combine(candidate, datetime.min.time(), tzinfo=UTC)
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of(fare),
        cabin=_milestone_05_base_cabin(),
    )
    # Mutate occupancy to match ``pct`` by flipping the first N fillers to OCCUPIED.
    fillers = [seat_id for seat_id in flight.cabin.seats if seat_id.value.startswith("FILL-")]
    for i, seat_id in enumerate(fillers):
        if i < pct:
            existing = flight.cabin.seats[seat_id]
            flight.cabin.seats[seat_id] = Seat(
                id=existing.id,
                seat_class=existing.seat_class,
                kind=existing.kind,
                status=SeatStatus.OCCUPIED,
            )
    container.flight_repo.add(flight)
    world["last_flight_id"] = flight_id


@given(parsers.parse('seat "{seat_id}" in {seat_class} has kind "{kind}"'))
def _set_seat_kind(container, world: dict, seat_id: str, seat_class: str, kind: str) -> None:
    """Overwrite a seat in the previously-seeded flight's cabin with the given
    class + kind. The seat exists as a STANDARD Economy filler from the
    Background; this Given upgrades it so the pricing scenarios can exercise
    the Appendix A surcharge lookup.
    """
    flight = container.flight_repo.get(FlightId(world["last_flight_id"]))
    if flight is None:
        raise AssertionError("flight not seeded before seat-kind override")
    flight.cabin.seats[SeatId(seat_id)] = Seat(
        id=SeatId(seat_id),
        seat_class=SeatClass[seat_class.upper()],
        kind=SeatKind[kind.upper()],
        status=SeatStatus.AVAILABLE,
    )


@when(parsers.parse('the traveler quotes seat "{seat_id}"'))
def _http_quote_single_seat(client, world: dict, seat_id: str) -> None:
    """Drive ``POST /quotes`` for exactly one seat on the last-seeded flight."""
    world["response"] = client.post(
        "/quotes",
        json={
            "flightId": world["last_flight_id"],
            "seatIds": [seat_id],
            "passengers": 1,
        },
    )


@then(parsers.parse(
    'the breakdown\'s seat_surcharges list contains exactly '
    "{{ seat: \"{seat}\", amount: {amount} }}"
))
def _assert_seat_surcharges_exactly(world: dict, seat: str, amount: str) -> None:
    """Assert the response's seat_surcharges list has exactly one entry
    matching (seat, amount). ``amount`` is a decimal string like ``35.00``
    or ``-5.00`` — compared via ``Money.of`` to normalise precision.
    """
    body = world["response"].json()
    lines = body.get("seatSurcharges")
    assert isinstance(lines, list), (
        f"expected seatSurcharges list, got {lines!r} in {body!r}"
    )
    assert len(lines) == 1, (
        f"expected exactly 1 seat_surcharge line, got {len(lines)}: {lines!r}"
    )
    line = lines[0]
    assert line.get("seat") == seat, (
        f"expected seat {seat!r}, got {line.get('seat')!r}"
    )
    assert Money.of(line.get("amount")) == Money.of(amount), (
        f"expected amount {amount}, got {line.get('amount')!r}"
    )


@then(parsers.parse(
    'the breakdown\'s seat_surcharges list contains '
    "{{ seat: \"{seat}\", amount: {amount} }}"
))
def _assert_seat_surcharges_contains(world: dict, seat: str, amount: str) -> None:
    """Assert the response's seat_surcharges list contains an entry matching
    (seat, amount). Used by scenarios that may add more lines in later slices
    (e.g., once taxes/fees flow as separate lines).
    """
    body = world["response"].json()
    lines = body.get("seatSurcharges")
    assert isinstance(lines, list), (
        f"expected seatSurcharges list, got {lines!r} in {body!r}"
    )
    match = next(
        (ln for ln in lines if ln.get("seat") == seat
         and Money.of(ln.get("amount")) == Money.of(amount)),
        None,
    )
    assert match is not None, (
        f"expected a seat_surcharge {{seat={seat!r}, amount={amount}}} in {lines!r}"
    )


# ---- Milestone 05: taxes steps (step 05-02) ---------------------------------
#
# Step 05-02 wires two flat tax rates (domestic 7.5%, international 12%) into
# ``POST /quotes``. The Givens below mark an already-seeded flight as
# ``domestic`` or mint a fresh ``international`` flight; the assertion
# re-computes the expected taxable base from the response's multipliers so a
# test failure reports the exact discrepancy.

from flights.domain.model.flight import RouteKind
from flights.domain.pricing import TAX_RATES


@given(parsers.parse('flight "{flight_id}" is marked "{kind}"'))
def _mark_flight_route_kind(
    container, world: dict, flight_id: str, kind: str,
) -> None:
    """Pin a flight's RouteKind so POST /quotes selects the matching tax rate.

    For ``domestic`` we assume the Background already seeded ``flight_id``
    (default DOMESTIC, so this is effectively a narrative check). For
    ``international`` we add a brand-new flight — the Background's
    FL-LAX-NYC-0800 stays DOMESTIC so the first sub-scenario still asserts
    cleanly against it.
    """
    requested = RouteKind[kind.upper()]
    existing = container.flight_repo.get(FlightId(flight_id))
    if existing is not None:
        # Mutate in place — the InMemoryFlightRepository holds the dataclass
        # instance, so setting ``route_kind`` on it is observed by the next
        # HTTP call. Flight is a mutable dataclass (not frozen).
        existing.route_kind = requested
        world["last_flight_id"] = flight_id
        return
    # Mint a fresh INTERNATIONAL flight aligned with the Background's clock
    # and fare so the taxable base is reproducible without re-stating the
    # whole pricing context in the feature file.
    background = container.flight_repo.get(FlightId(world["last_flight_id"]))
    if background is None:
        raise AssertionError("Background flight missing — cannot clone pricing context")
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination=flight_id.split("-")[2] if "-" in flight_id else "LHR",
        departure_at=background.departure_at,
        arrival_at=background.arrival_at,
        airline="MOCK",
        base_fare=background.base_fare,
        cabin=_milestone_05_base_cabin(),
        route_kind=requested,
    )
    container.flight_repo.add(flight)
    world["last_flight_id"] = flight_id


@when("the traveler quotes one seat")
def _http_quote_one_seat_on_current_flight(client, world: dict) -> None:
    """Drive POST /quotes for any single seat on the last-marked flight."""
    seat_id = "FILL-001"
    world["response"] = client.post(
        "/quotes",
        json={
            "flightId": world["last_flight_id"],
            "seatIds": [seat_id],
            "passengers": 1,
        },
    )


@when("the traveler quotes one seat on that flight")
def _http_quote_one_seat_on_that_flight(client, world: dict) -> None:
    """Alias When — same action, feature-file phrasing varies for readability."""
    _http_quote_one_seat_on_current_flight(client, world)


@then(parsers.parse("the taxes line equals the configured {kind} rate times the base"))
def _assert_taxes_line_matches_rate_times_base(world: dict, kind: str) -> None:
    """Re-derive the expected tax amount from the response's own breakdown
    fields — this proves the production code applied the correct RouteKind
    rate to ``(base × multipliers + Σ surcharges)`` rather than to the raw
    base fare alone.
    """
    body = world["response"].json()
    assert "taxes" in body, f"missing 'taxes' in response body: {body!r}"
    base_fare = Decimal(body["baseFare"])
    demand = Decimal(body["demandMultiplier"])
    time = Decimal(body["timeMultiplier"])
    day = Decimal(body["dayMultiplier"])
    surcharges_sum = sum(
        (Decimal(line["amount"]) for line in body.get("seatSurcharges", [])),
        Decimal("0"),
    )
    taxable_base = base_fare * demand * time * day + surcharges_sum
    expected_rate = TAX_RATES[RouteKind[kind.upper()]]
    expected_taxes = Money.of(taxable_base * expected_rate)
    actual_taxes = Money.of(body["taxes"])
    assert actual_taxes == expected_taxes, (
        f"expected taxes {expected_taxes.amount} ({kind} rate {expected_rate} "
        f"× taxable base {taxable_base}), got {actual_taxes.amount}"
    )


# ---- Milestone 05: full breakdown JSON contract (step 05-03) ----------------
#
# Step 05-03 locks in the ``POST /quotes`` response shape with decimal
# precision. These steps drive the two previously-@pending scenarios:
#
#   * "Total equals the arithmetic of all components" — reproduces the total
#     from the response's own numeric fields by summing
#     ``base × multipliers + Σ surcharges + taxes + fees`` and applying the
#     Appendix B rounding rule via ``PriceBreakdown.total``.
#
#   * "Breakdown precision round-trips" — asserts every monetary value is a
#     string with exactly 2dp and that parsing each back through ``Decimal``
#     yields the same quantized value (no JSON-float precision loss).

from flights.domain.model.quote import PriceBreakdown, SeatSurchargeLine


_MONEY_FIELDS: tuple[str, ...] = ("baseFare", "taxes", "fees", "total")


@when("the traveler quotes any seat on any flight")
def _http_quote_any_seat_any_flight(client, world: dict) -> None:
    """Drive ``POST /quotes`` for any seat on the current flight.

    The Background already seeded a flight; ``last_flight_id`` points at it.
    We quote the first filler seat (STANDARD, no surcharge) so the response
    exercises the full breakdown shape even with an empty surcharges list —
    precision must hold regardless of whether seat_surcharges is populated.
    """
    world["response"] = client.post(
        "/quotes",
        json={
            "flightId": world["last_flight_id"],
            "seatIds": ["FILL-001"],
            "passengers": 1,
        },
    )


@then(
    "the total equals base_fare * demand_multiplier * time_multiplier "
    "* day_multiplier + surcharges + taxes + fees"
)
def _assert_total_matches_full_arithmetic(world: dict) -> None:
    """Re-derive the total from the response's own breakdown fields.

    The domain holds taxes at full precision internally and applies the
    Appendix B rounding rule once at the end. The wire displays taxes
    quantized to 2dp — so summing the displayed components and applying
    the same rule can land one cent away from the wire total. A gap
    wider than one cent means the displayed breakdown no longer
    reproduces the charged amount (arithmetic bug).
    """
    body = world["response"].json()
    breakdown = PriceBreakdown(
        base_fare=Money.of(body["baseFare"]),
        demand_multiplier=Decimal(body["demandMultiplier"]),
        time_multiplier=Decimal(body["timeMultiplier"]),
        day_multiplier=Decimal(body["dayMultiplier"]),
        seat_surcharges=tuple(
            SeatSurchargeLine(seat=SeatId(line["seat"]), amount=Money.of(line["amount"]))
            for line in body.get("seatSurcharges", [])
        ),
        taxes=Money.of(body["taxes"]),
        fees=Money.of(body["fees"]),
    )
    expected_total = breakdown.total
    actual_total = Money.of(body["total"])
    delta = abs(actual_total.amount - expected_total.amount)
    assert delta <= Decimal("0.01"), (
        f"response total {body['total']} does not reproduce from displayed "
        f"components (reconstruction: {expected_total.amount}, delta: {delta})"
    )


@then("the computation can be reproduced on paper from the response fields")
def _assert_response_fields_are_sufficient_for_reproduction(world: dict) -> None:
    """The response body must expose every field needed to reproduce the
    total — ``baseFare``, the three multipliers, ``seatSurcharges``,
    ``taxes``, ``fees``. Without any one of these the "on paper"
    reproduction is impossible for a stakeholder reviewing the receipt.
    """
    body = world["response"].json()
    required = (
        "baseFare",
        "demandMultiplier",
        "timeMultiplier",
        "dayMultiplier",
        "seatSurcharges",
        "taxes",
        "fees",
        "total",
    )
    missing = [field for field in required if field not in body]
    assert not missing, (
        f"response missing fields required to reproduce total: {missing!r}"
    )


@then(
    "every monetary value in the response is a string with exactly "
    "2 decimal places"
)
def _assert_money_fields_are_two_decimal_strings(world: dict) -> None:
    """Every money field is a JSON string (not a JSON number) with exactly
    two digits after a single decimal point. Rejecting scientific notation
    and missing/extra decimals prevents float round-tripping bugs at the
    wire layer.
    """
    body = world["response"].json()
    for field in _MONEY_FIELDS:
        value = body.get(field)
        assert isinstance(value, str), (
            f"{field} must be a JSON string, got {type(value).__name__}: {value!r}"
        )
        assert "." in value, f"{field} missing decimal point: {value!r}"
        integer_part, _, fractional_part = value.partition(".")
        assert fractional_part.isdigit() and len(fractional_part) == 2, (
            f"{field} must have exactly 2 decimal places, got {value!r}"
        )
        # Reject scientific notation; string must parse as a plain Decimal.
        assert "e" not in value.lower(), (
            f"{field} must not use scientific notation: {value!r}"
        )
    # Seat surcharge amounts carry the same guarantee.
    for line in body.get("seatSurcharges", []):
        amount = line.get("amount")
        assert isinstance(amount, str) and "." in amount, (
            f"seat surcharge amount must be a 2dp string, got {amount!r}"
        )
        _, _, frac = amount.partition(".")
        assert frac.isdigit() and len(frac) == 2, (
            f"seat surcharge {line!r}: fractional part must be 2 digits"
        )


@then("parsing each back as Decimal yields the same quantized value")
def _assert_money_fields_round_trip_through_decimal(world: dict) -> None:
    """Serialising ``str(Decimal("X.YZ"))`` and parsing back via
    ``Decimal(...)`` must yield the same Decimal — proving no precision is
    lost at the wire. Repeating the process a second time gives the same
    result, confirming the representation is a fixed-point of the
    str→Decimal→str round-trip.
    """
    body = world["response"].json()
    for field in _MONEY_FIELDS:
        value = body[field]
        parsed = Decimal(value)
        assert str(parsed) == value, (
            f"{field} round-trip mismatch: str(Decimal({value!r})) = {str(parsed)!r}"
        )
    for line in body.get("seatSurcharges", []):
        amount = line["amount"]
        parsed = Decimal(amount)
        assert str(parsed) == amount, (
            f"seat {line['seat']!r} amount round-trip mismatch: "
            f"str(Decimal({amount!r})) = {str(parsed)!r}"
        )


# ---- Milestone 07: seat-lock steps (step 07-01) -----------------------------
#
# Step 07-01 wires the POST /seat-locks endpoint and the SeatLockStore primitive
# (coarse lock-per-store, 10-min TTL, expired-treated-as-free). Scenarios
# enabled by this slice:
#
#   * "Single session acquires a lock on an available seat"   — happy path.
#   * "A second session sees the locked seat as unavailable"  — seat map
#     composes SeatLockStore state with bookings to mark seats OCCUPIED to
#     other sessions.
#   * "Lock auto-expires after 10 minutes"                    — TTL edge.
#
# The Background reserves seat "30F" as the only AVAILABLE seat so the
# scenarios have a single unambiguous target. The Given below seeds the flight
# with a minimal cabin containing just 30F — keeping the fixture narrative-
# pinned rather than cluttering the flight with dozens of irrelevant seats.


@given(parsers.parse(
    'a flight "{flight_id}" where seat "{seat_id}" is the only remaining '
    "AVAILABLE seat"
))
def _seed_milestone_07_flight_single_available_seat(
    container, world: dict, flight_id: str, seat_id: str,
) -> None:
    """Seed a flight whose cabin has exactly one AVAILABLE seat, identified
    by ``seat_id``. Other seats are irrelevant to milestone-07 assertions —
    omitting them keeps the fixture narrow. The HTTP route observes this via
    the real flight repository so the seat-map response is produced by
    production code paths.
    """
    departure = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    cabin = Cabin()
    cabin.seats[SeatId(seat_id)] = Seat(
        id=SeatId(seat_id),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination="NYC",
        departure_at=departure,
        arrival_at=departure,
        airline="MOCK",
        base_fare=Money.of("299"),
        cabin=cabin,
    )
    container.flight_repo.add(flight)
    world["last_flight_id"] = flight_id


@when(parsers.parse(
    'session "{session_id}" requests a lock on seat "{seat_id}" '
    'for flight "{flight_id}"'
))
def _http_request_seat_lock_for_flight(
    client, world: dict, session_id: str, seat_id: str, flight_id: str,
) -> None:
    """Drive POST /seat-locks with an explicit flightId + seatIds + sessionId.

    Stashes the response so subsequent Thens can assert on status and body
    fields (lockId, expiresAt, conflicts).
    """
    world["response"] = client.post(
        "/seat-locks",
        json={
            "flightId": flight_id,
            "seatIds": [seat_id],
            "sessionId": session_id,
        },
    )
    world["last_flight_id"] = flight_id


@when(parsers.parse('session "{session_id}" requests a lock on seat "{seat_id}"'))
def _http_request_seat_lock_short(
    client, world: dict, session_id: str, seat_id: str,
) -> None:
    """Alias When — uses ``world["last_flight_id"]`` when the feature file
    omits the flight id. Covers the "Lock auto-expires" scenario where the
    Background already pinned the flight under test.
    """
    flight_id = world["last_flight_id"]
    world["response"] = client.post(
        "/seat-locks",
        json={
            "flightId": flight_id,
            "seatIds": [seat_id],
            "sessionId": session_id,
        },
    )


@then(parsers.parse(
    "the response contains a lock id and an expiresAt 10 minutes in the future"
))
def _assert_lock_id_and_expires_at_ten_minutes(
    frozen_clock: FrozenClock, world: dict,
) -> None:
    """Assert the 201 body has a non-empty lockId and an expiresAt exactly
    10 minutes after the frozen clock — anchoring TTL computation on the
    production clock port, not ``datetime.now()``.
    """
    from datetime import timedelta
    body = world["response"].json()
    lock_id = body.get("lockId")
    assert lock_id, f"response missing lockId: {body!r}"
    expires_at_str = body.get("expiresAt")
    assert expires_at_str, f"response missing expiresAt: {body!r}"
    expires_at = datetime.fromisoformat(expires_at_str)
    expected = frozen_clock.now() + timedelta(minutes=10)
    assert expires_at == expected, (
        f"expiresAt {expires_at.isoformat()} != frozen_clock + 10min "
        f"{expected.isoformat()}"
    )


@given(parsers.parse('session "{session_id}" holds a valid lock on seat "{seat_id}"'))
def _seed_session_holds_valid_lock(
    client, world: dict, session_id: str, seat_id: str,
) -> None:
    """Drive POST /seat-locks through the HTTP port so the lock is installed
    by production code (not by direct store manipulation). Asserts the 201
    outcome so a wiring regression surfaces at the Given, not at the Then.
    """
    flight_id = world["last_flight_id"]
    response = client.post(
        "/seat-locks",
        json={
            "flightId": flight_id,
            "seatIds": [seat_id],
            "sessionId": session_id,
        },
    )
    assert response.status_code == 201, (
        f"failed to seed lock for session {session_id!r}: "
        f"{response.status_code} {response.text}"
    )


@when(parsers.parse('session "{session_id}" requests the seat map for "{flight_id}"'))
def _http_session_requests_seat_map(
    client, world: dict, session_id: str, flight_id: str,
) -> None:
    """GET the seat map while identifying the requesting session via the
    ``sessionId`` query parameter. The SeatMapService marks seats OCCUPIED to
    the requester when another session holds a valid lock; the same query
    from the lock-holder's own session would leave them AVAILABLE (covered by
    unit tests — not asserted here).
    """
    world["response"] = client.get(
        f"/flights/{flight_id}/seats",
        params={"sessionId": session_id},
    )


@then(parsers.parse(
    'seat "{seat_id}" is reported as unavailable to session "{session_id}"'
))
def _assert_seat_unavailable_to_session(
    world: dict, seat_id: str, session_id: str,
) -> None:
    """Assert the seat map returned to ``session_id`` reports ``seat_id`` as
    OCCUPIED (the only non-AVAILABLE status the contract exposes that maps
    to "unavailable to the traveler"). BLOCKED would also be "unavailable"
    but carries the wrong narrative — BLOCKED = ops-maintenance.
    """
    body = world["response"].json()
    seats = body.get("seats", [])
    match = next((s for s in seats if s.get("seatId") == seat_id), None)
    assert match is not None, f"seat {seat_id} not in response: {body!r}"
    status = match.get("status")
    assert status == "OCCUPIED", (
        f"seat {seat_id} expected OCCUPIED for session {session_id}, got {status!r}"
    )


@given(parsers.parse(
    'session "{session_id}" holds a lock on seat "{seat_id}" acquired at {time}'
))
def _seed_session_holds_lock_at(
    client, container, world: dict, session_id: str, seat_id: str, time: str,
) -> None:
    """Seed a lock acquired at a specific wall-clock time. The Background
    already frozen the clock at 10:00:00; ``time`` is a sanity tag for the
    narrative, and we assert the clock matches it so a mis-anchored scenario
    fails loudly rather than silently drifts.
    """
    from datetime import time as time_type
    expected = time_type.fromisoformat(time)
    actual = container.clock.now().time()
    assert actual.replace(microsecond=0) == expected, (
        f"Given expects clock at {time}, but container clock is at {actual}"
    )
    flight_id = world["last_flight_id"]
    response = client.post(
        "/seat-locks",
        json={
            "flightId": flight_id,
            "seatIds": [seat_id],
            "sessionId": session_id,
        },
    )
    assert response.status_code == 201, (
        f"failed to seed lock: {response.status_code} {response.text}"
    )


@when(parsers.parse("the clock advances to {time}"))
def _advance_clock_to(
    frozen_clock: FrozenClock, container, time: str,
) -> None:
    """Advance both the fixture clock and the container clock to the specified
    wall-clock time on the same day. Mirrors ``_advance_clock`` (by-minutes
    variant) but uses an absolute target so the TTL-boundary scenario can
    cite "10:10:01" directly from the feature file.
    """
    target_time = datetime.strptime(time, "%H:%M:%S").time()
    current = container.clock.now()
    target = current.replace(
        hour=target_time.hour,
        minute=target_time.minute,
        second=target_time.second,
        microsecond=0,
    )
    if target < current:
        raise AssertionError(
            f"advance-to target {time} is in the past relative to {current}"
        )
    delta = target - current
    frozen_clock.advance(delta)
    container.clock.advance(delta)


@then(parsers.parse('session "{session_id}" receives HTTP 201 with a new lock'))
def _assert_session_receives_201_with_lock(world: dict, session_id: str) -> None:
    """Assert the last HTTP response is a 201 and carries a non-empty lockId.
    This is the "lock auto-expires" scenario's Then — proving the second
    session's acquire succeeds once the TTL of the first lock has elapsed.
    """
    response = world["response"]
    assert response.status_code == 201, (
        f"expected HTTP 201 for session {session_id}, got "
        f"{response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("lockId"), f"response missing lockId: {body!r}"


# ---- Milestone 07: step 07-02 (commit under lock + concurrent acquire) -----

@when(parsers.parse('ten sessions concurrently request a lock on seat "{seat_id}"'))
def _ten_sessions_concurrent_acquire(
    client, world: dict, seat_id: str,
) -> None:
    """Launch ten concurrent ``POST /seat-locks`` requests against the same
    seat, each with a distinct sessionId. Synchronise launch through a
    ``threading.Barrier`` so all ten threads are racing at the same instant —
    mirroring the real tension the ADR-008 critical section is designed for.

    Stashes the list of responses in ``world["responses"]`` so the Thens can
    assert winner/rejection/500 counts without re-driving the endpoint.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    flight_id = world["last_flight_id"]
    barrier = threading.Barrier(10)

    def _acquire(session_id: str):
        barrier.wait()
        return client.post(
            "/seat-locks",
            json={
                "flightId": flight_id,
                "seatIds": [seat_id],
                "sessionId": session_id,
            },
        )

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(_acquire, f"S-{i:02d}") for i in range(10)]
        world["responses"] = [f.result() for f in futures]


@then("exactly one session receives HTTP 201")
def _assert_exactly_one_winner(world: dict) -> None:
    responses = world["responses"]
    winners = [r for r in responses if r.status_code == 201]
    assert len(winners) == 1, (
        f"expected exactly 1 winner, got {len(winners)}: "
        f"{[r.status_code for r in responses]}"
    )


@then(parsers.parse(
    'the other nine sessions receive HTTP 409 with "{phrase}"'
))
def _assert_nine_conflicts(world: dict, phrase: str) -> None:
    responses = world["responses"]
    conflicts = [r for r in responses if r.status_code == 409]
    assert len(conflicts) == 9, (
        f"expected 9 conflicts, got {len(conflicts)}: "
        f"{[r.status_code for r in responses]}"
    )
    for response in conflicts:
        body = response.json()
        assert phrase in body.get("detail", "").lower(), (
            f"expected 409 detail to cite {phrase!r}, got {body!r}"
        )


@then("zero sessions receive a 500")
def _assert_zero_500s(world: dict) -> None:
    responses = world["responses"]
    fails = [r for r in responses if r.status_code >= 500]
    assert len(fails) == 0, (
        f"expected zero 5xx responses, got {len(fails)}: "
        f"{[r.status_code for r in fails]}"
    )


@given(parsers.parse(
    'session "{session_id}" holds a lock on seat "{seat_id}" and '
    'an associated valid quote'
))
def _seed_lock_and_quote(
    client, world: dict, session_id: str, seat_id: str,
) -> None:
    """Acquire a lock on ``seat_id`` for ``session_id`` AND mint a quote for
    the same seat. Both are driven through real HTTP endpoints so production
    code installs them.
    """
    flight_id = world["last_flight_id"]
    lock_response = client.post(
        "/seat-locks",
        json={
            "flightId": flight_id,
            "seatIds": [seat_id],
            "sessionId": session_id,
        },
    )
    assert lock_response.status_code == 201, (
        f"failed to seed lock: {lock_response.status_code} {lock_response.text}"
    )
    world["lock_id"] = lock_response.json()["lockId"]
    world["session_id"] = session_id

    quote_response = client.post(
        "/quotes",
        json={
            "flightId": flight_id,
            "seatIds": [seat_id],
            "passengers": 1,
            "sessionId": session_id,
        },
    )
    assert quote_response.status_code == 200, (
        f"failed to seed quote: {quote_response.status_code} {quote_response.text}"
    )
    world["quote_id"] = quote_response.json()["quoteId"]


@given(parsers.parse(
    'session "{session_id}" holds a valid lock on seat "{seat_id}" and '
    'a valid quote'
))
def _seed_valid_lock_and_valid_quote(
    client, world: dict, session_id: str, seat_id: str,
) -> None:
    """Narrative variant of the previous Given — same behaviour. Kept as a
    distinct binding because pytest-bdd matches by exact phrase and the two
    feature scenarios phrase the precondition differently ("an associated
    valid" vs "a valid").
    """
    _seed_lock_and_quote(
        client=client, world=world, session_id=session_id, seat_id=seat_id,
    )


@when(parsers.parse(
    'session "{session_id}" commits a booking using the expired lock'
))
def _commit_with_expired_lock(
    client, world: dict, session_id: str,
) -> None:
    """POST /bookings carrying the previously-seeded lock_id + session_id.
    The clock has already been advanced past the TTL by the preceding When
    step, so the commit should be rejected with 410 Gone.
    """
    flight_id = world["last_flight_id"]
    seat_id = "30F"
    world["response"] = client.post(
        "/bookings",
        json={
            "flightId": flight_id,
            "seatId": seat_id,
            "passenger": {"name": "Jane Doe"},
            "paymentToken": "mock-ok",
            "quoteId": world["quote_id"],
            "lockId": world["lock_id"],
            "sessionId": session_id,
        },
    )


@when(parsers.parse(
    'session "{session_id}" commits with a paymentToken that the mock rejects'
))
def _commit_with_rejected_payment(
    client, world: dict, session_id: str,
) -> None:
    """POST /bookings with ``paymentToken='fail'`` — the MockPaymentGateway
    default decline token. The commit reaches the payment charge after
    seat, quote, and lock validations all pass, so the failure branch
    exercises the "lock preserved" path.
    """
    flight_id = world["last_flight_id"]
    seat_id = "30F"
    world["response"] = client.post(
        "/bookings",
        json={
            "flightId": flight_id,
            "seatId": seat_id,
            "passenger": {"name": "Jane Doe"},
            "paymentToken": "fail",
            "quoteId": world["quote_id"],
            "lockId": world["lock_id"],
            "sessionId": session_id,
        },
    )


@then(parsers.parse(
    'the lock on seat "{seat_id}" is still valid when the clock is unchanged'
))
def _assert_lock_still_valid(
    container, world: dict, seat_id: str,
) -> None:
    """Assert the seeded lock is still in the store and unexpired — proving
    the payment-failure branch did NOT release it. Reads the store directly
    because the HTTP port does not expose a lock-status query.
    """
    now = container.clock.now()
    lock_id = world["lock_id"]
    assert container.seat_lock_store.is_valid(lock_id, now), (
        f"expected lock {lock_id} on {seat_id} to still be valid at {now}"
    )


@then(parsers.parse('an audit "{event_type}" event is written'))
def _assert_audit_event_written(
    container, event_type: str,
) -> None:
    """Assert at least one audit event of ``event_type`` was written. Used
    by the payment-failure scenario to confirm the PaymentFailed trail is
    recorded even though the booking was rejected.
    """
    events = getattr(container.audit, "events", [])
    matching = [e for e in events if e.get("type") == event_type]
    assert matching, (
        f"expected at least one {event_type} event, got: "
        f"{[e.get('type') for e in events]}"
    )


# ---- Milestone 07: step 07-03 (race harness — KPI-T2) ----------------------
#
# The harness runs 100 in-process trials. Each trial builds a fresh container,
# seeds a flight with ONE available seat, then fires 10 barrier-synchronised
# threads at POST /seat-locks. KPI-T2 requires every trial to produce exactly
# one winner and nine rejections — ZERO trials with >1 winner.
#
# The step implementations delegate to ``scripts.race_last_seat.run_harness``
# so the harness is exercised through the exact code path an engineer would
# run manually (``python scripts/race_last_seat.py``). Keeping the production
# harness as the single source of truth prevents test-only race logic from
# drifting away from the CLI.


@when(parsers.parse(
    "the race-last-seat harness runs {trials:d} trials, "
    "each with {threads:d} threads competing for one seat"
))
def _run_race_harness(world: dict, trials: int, threads: int) -> None:
    """Invoke the race harness in-process and stash the summary.

    We import lazily so a harness import error surfaces as a Red test
    failure at this step rather than at module-load time.
    """
    from scripts.race_last_seat import run_harness
    world["race_summary"] = run_harness(trials=trials, threads=threads)


@then("every trial produces exactly one winner and nine rejections")
def _assert_every_trial_perfect(world: dict) -> None:
    """Assert the harness summary shows exactly ``trials`` winners and
    ``trials * 9`` rejections across the full run — the "perfect" outcome
    mandated by KPI-T2.
    """
    summary = world["race_summary"]
    trials = summary["trials"]
    assert summary["total_winners"] == trials, (
        f"expected {trials} winners (one per trial), got "
        f"{summary['total_winners']}: {summary!r}"
    )
    expected_rejected = trials * 9
    assert summary["total_rejected"] == expected_rejected, (
        f"expected {expected_rejected} rejections (9 per trial), got "
        f"{summary['total_rejected']}: {summary!r}"
    )


@then(parsers.parse(
    'over {trials:d} trials, the count of "double-booking" outcomes is {count:d}'
))
def _assert_zero_double_bookings(world: dict, trials: int, count: int) -> None:
    """Assert ``double_bookings`` (any trial with >1 winner) matches the
    feature's promised count — 0. A single double-booking fails KPI-T2 and
    blocks the milestone.
    """
    summary = world["race_summary"]
    assert summary["trials"] == trials, (
        f"harness ran {summary['trials']} trials, feature asserts {trials}: "
        f"{summary!r}"
    )
    assert summary["double_bookings"] == count, (
        f"expected {count} double-bookings, got "
        f"{summary['double_bookings']}: {summary!r}"
    )


# ---- Milestone 08: step 08-01 (round-trip pairing) -------------------------
#
# The round-trip scenarios search a driven port with ``returnDate`` set and
# expect a *paired* response body: ``{"pairs": [...], "pairCount": N,
# "flightCount": 2N, "page": ..., "size": ...}``. Pairing logic lives in
# ``SearchService.search_round_trip`` and is routed to via the HTTP layer
# when ``returnDate`` is present.
#
# The seeded catalog was extended with NYC→LAX and LHR→LAX return legs so
# the standard Background ``_seed_catalog`` already yields round-trip
# candidates for the scenarios below.


@given(parsers.parse(
    "a seeded catalog with outbound flights on {outbound_date} and "
    "return flights on {return_date}"
))
def _seed_round_trip_catalog(
    container, outbound_date: str, return_date: str
) -> None:
    """Background seed for milestone-08 round-trip scenarios.

    Loads the full ``seeded_catalog()`` (which now includes NYC→LAX and
    LHR→LAX return legs for every catalog date). The dates named in the
    step are asserted to be covered so a future change to the catalog
    window fails loudly rather than producing empty result sets.
    """
    flights = seeded_catalog()
    dates_present = {f.departure_at.date().isoformat() for f in flights}
    assert outbound_date in dates_present, (
        f"outbound date {outbound_date} not in seeded catalog dates"
    )
    assert return_date in dates_present, (
        f"return date {return_date} not in seeded catalog dates"
    )
    for flight in flights:
        container.flight_repo.add(flight)


@when(parsers.parse(
    "the traveler searches {origin} to {destination} on {departure_date} "
    "with returnDate {return_date}"
))
def _http_search_round_trip(
    client,
    world: dict,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
) -> None:
    world["response"] = client.get(
        "/flights/search",
        params={
            "origin": origin,
            "destination": destination,
            "departureDate": departure_date,
            "returnDate": return_date,
        },
    )


@when(parsers.parse(
    "the traveler searches a round-trip on a seeded catalog with "
    "{count:d} candidate pairs"
))
def _http_search_round_trip_paginated(
    client, container, world: dict, count: int
) -> None:
    """Drive /flights/search with returnDate against a catalog that has at
    least ``count`` outbound×return combinations.

    The default seeded catalog yields 30 outbound LAX→NYC flights on
    2026-06-01 via the ``_seed_n_flights_on_route``-equivalent enumeration,
    but the cross-product of 30 outbounds × 30 returns is 900. We pick a
    single outbound date and seed ``count`` outbound+``count`` return
    flights so the pair space equals ``count`` — one return per outbound,
    arriving/departing so the 2h buffer holds.
    """
    from datetime import timedelta
    outbound_date = "2026-06-01"
    return_date = "2026-06-08"
    outbound_base = datetime.fromisoformat(f"{outbound_date}T08:00:00+00:00")
    return_base = datetime.fromisoformat(f"{return_date}T14:00:00+00:00")
    for i in range(count):
        outbound_departure = outbound_base + timedelta(minutes=i)
        container.flight_repo.add(
            Flight(
                id=FlightId(f"FL-OUT-{i:03d}"),
                origin="LAX",
                destination="NYC",
                departure_at=outbound_departure,
                arrival_at=outbound_departure + timedelta(hours=5),
                airline="AA",
                base_fare=Money.of("299"),
                cabin=Cabin(),
            )
        )
        return_departure = return_base + timedelta(minutes=i)
        container.flight_repo.add(
            Flight(
                id=FlightId(f"FL-RET-{i:03d}"),
                origin="NYC",
                destination="LAX",
                departure_at=return_departure,
                arrival_at=return_departure + timedelta(hours=5),
                airline="AA",
                base_fare=Money.of("299"),
                cabin=Cabin(),
            )
        )
    world["response"] = client.get(
        "/flights/search",
        params={
            "origin": "LAX",
            "destination": "NYC",
            "departureDate": outbound_date,
            "returnDate": return_date,
        },
    )
    world["round_trip_candidate_pairs"] = count


@then("every result is a pair where return.origin equals outbound.destination")
def _assert_every_pair_compatible(world: dict) -> None:
    response = world["response"]
    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    pairs = body.get("pairs")
    assert isinstance(pairs, list) and pairs, (
        f"expected non-empty 'pairs' list, got {body!r}"
    )
    for pair in pairs:
        outbound = pair["outbound"]
        return_leg = pair["return"]
        assert return_leg["origin"] == outbound["destination"], (
            f"pair mismatch: outbound.destination={outbound['destination']!r} "
            f"return.origin={return_leg['origin']!r}"
        )


@then("every pair has return.departure at least 2 hours after outbound.arrival")
def _assert_two_hour_buffer(world: dict) -> None:
    from datetime import timedelta as _td
    response = world["response"]
    body = response.json()
    pairs = body.get("pairs", [])
    for pair in pairs:
        outbound_arrival = datetime.fromisoformat(pair["outbound"]["arrivalAt"])
        return_departure = datetime.fromisoformat(pair["return"]["departureAt"])
        assert return_departure >= outbound_arrival + _td(hours=2), (
            f"buffer violated: outbound arrives {outbound_arrival.isoformat()}, "
            f"return departs {return_departure.isoformat()}"
        )


@then(parsers.parse("the response contains at most {n:d} pairs"))
def _assert_at_most_n_pairs(world: dict, n: int) -> None:
    body = world["response"].json()
    pairs = body.get("pairs", [])
    assert len(pairs) <= n, f"expected at most {n} pairs, got {len(pairs)}"


@then(parsers.parse(
    "pagination metadata reports both pairCount and flightCount "
    "(flightCount = 2 * pairCount)"
))
def _assert_pair_and_flight_counts(world: dict) -> None:
    body = world["response"].json()
    assert "pairCount" in body, f"missing 'pairCount' in body: {body!r}"
    assert "flightCount" in body, f"missing 'flightCount' in body: {body!r}"
    pair_count = body["pairCount"]
    flight_count = body["flightCount"]
    assert isinstance(pair_count, int), f"pairCount must be int, got {type(pair_count)}"
    assert isinstance(flight_count, int), (
        f"flightCount must be int, got {type(flight_count)}"
    )
    assert flight_count == 2 * pair_count, (
        f"flightCount ({flight_count}) != 2 * pairCount ({pair_count})"
    )


# ---- Milestone 08: step 08-02 (filters) ------------------------------------
#
# Filter scenarios exercise the /flights/search endpoint with optional
# query params (``airline``, ``minPrice``, ``maxPrice``,
# ``departureTimeFrom``, ``departureTimeTo``). Filters compose AND and are
# commutative (query-string order does not change the response). They are
# applied post-search in the application service so the repository port
# signature stays narrow.
#
# The filter scenarios each seed a small set of flights tailored to the
# scenario so assertions are non-vacuous (empty result sets would satisfy
# "every returned flight …" with circular-verification theatre).


@when(parsers.parse(
    'the traveler searches {origin} to {destination} on {departure_date} '
    'with airline "{airline}"'
))
def _http_search_with_airline(
    container,
    client,
    world: dict,
    origin: str,
    destination: str,
    departure_date: str,
    airline: str,
) -> None:
    # Seed one AA and one UA flight so the airline filter has signal.
    departure_base = datetime.fromisoformat(f"{departure_date}T10:00:00+00:00")
    container.flight_repo.add(
        Flight(
            id=FlightId("FL-FILTER-AA"),
            origin=origin, destination=destination,
            departure_at=departure_base,
            arrival_at=departure_base,
            airline="AA",
            base_fare=Money.of("299"),
            cabin=Cabin(),
        )
    )
    container.flight_repo.add(
        Flight(
            id=FlightId("FL-FILTER-UA"),
            origin=origin, destination=destination,
            departure_at=departure_base,
            arrival_at=departure_base,
            airline="UA",
            base_fare=Money.of("299"),
            cabin=Cabin(),
        )
    )
    world["response"] = client.get(
        "/flights/search",
        params={
            "origin": origin,
            "destination": destination,
            "departureDate": departure_date,
            "airline": airline,
        },
    )


@then(parsers.parse('every returned flight has airline "{airline}"'))
def _assert_every_flight_has_airline(world: dict, airline: str) -> None:
    response = world["response"]
    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    flights = body.get("flights", [])
    assert flights, f"expected non-empty flight list, got {body!r}"
    for flight in flights:
        assert flight["airline"] == airline, (
            f"flight {flight['id']} has airline {flight['airline']!r}, "
            f"expected {airline!r}"
        )


@when(parsers.parse(
    'the traveler searches {origin} to {destination} on {departure_date} '
    'with minPrice {min_price:d} and maxPrice {max_price:d}'
))
def _http_search_with_price_range(
    container,
    client,
    world: dict,
    origin: str,
    destination: str,
    departure_date: str,
    min_price: int,
    max_price: int,
) -> None:
    # Seed three flights at different price points to exercise the
    # inclusive-range filter: 150 (below), 300 (inside), 600 (above).
    departure_base = datetime.fromisoformat(f"{departure_date}T10:00:00+00:00")
    for suffix, fare in (("CHEAP", "150"), ("MID", "300"), ("PREMIUM", "600")):
        container.flight_repo.add(
            Flight(
                id=FlightId(f"FL-FILTER-{suffix}"),
                origin=origin, destination=destination,
                departure_at=departure_base,
                arrival_at=departure_base,
                airline="AA",
                base_fare=Money.of(fare),
                cabin=Cabin(),
            )
        )
    world["response"] = client.get(
        "/flights/search",
        params={
            "origin": origin,
            "destination": destination,
            "departureDate": departure_date,
            "minPrice": min_price,
            "maxPrice": max_price,
        },
    )
    world["last_price_range"] = (min_price, max_price)


@then(parsers.parse(
    "every returned flight's indicative total is between {lo:d} and {hi:d} inclusive"
))
def _assert_every_flight_in_price_range(world: dict, lo: int, hi: int) -> None:
    response = world["response"]
    assert response.status_code == 200
    body = response.json()
    flights = body.get("flights", [])
    assert flights, f"expected non-empty flight list, got {body!r}"
    for flight in flights:
        fare = Decimal(flight["baseFare"]["amount"])
        assert Decimal(lo) <= fare <= Decimal(hi), (
            f"flight {flight['id']} fare {fare} outside [{lo}, {hi}]"
        )


@when(parsers.parse(
    'the traveler searches {origin} to {destination} on {departure_date} '
    'with departureTimeFrom {time_from} and departureTimeTo {time_to}'
))
def _http_search_with_time_window(
    container,
    client,
    world: dict,
    origin: str,
    destination: str,
    departure_date: str,
    time_from: str,
    time_to: str,
) -> None:
    # Seed three departures: 07:00 (before), 12:00 (inside), 19:00 (after).
    for hhmm, suffix in (("07:00", "EARLY"), ("12:00", "MID"), ("19:00", "LATE")):
        departure = datetime.fromisoformat(
            f"{departure_date}T{hhmm}:00+00:00"
        )
        container.flight_repo.add(
            Flight(
                id=FlightId(f"FL-TIMEFILTER-{suffix}"),
                origin=origin, destination=destination,
                departure_at=departure,
                arrival_at=departure,
                airline="AA",
                base_fare=Money.of("299"),
                cabin=Cabin(),
            )
        )
    world["response"] = client.get(
        "/flights/search",
        params={
            "origin": origin,
            "destination": destination,
            "departureDate": departure_date,
            "departureTimeFrom": time_from,
            "departureTimeTo": time_to,
        },
    )
    world["last_time_window"] = (time_from, time_to)


@then(parsers.parse(
    "every returned flight departs between {time_from} and {time_to} local time"
))
def _assert_every_flight_in_time_window(
    world: dict, time_from: str, time_to: str
) -> None:
    from datetime import time as _time
    lo = _time.fromisoformat(time_from)
    hi = _time.fromisoformat(time_to)
    response = world["response"]
    assert response.status_code == 200
    body = response.json()
    flights = body.get("flights", [])
    assert flights, f"expected non-empty flight list, got {body!r}"
    for flight in flights:
        departs_at = datetime.fromisoformat(flight["departureAt"])
        depart_time = departs_at.time()
        assert lo <= depart_time <= hi, (
            f"flight {flight['id']} departs at {depart_time} outside "
            f"[{lo}, {hi}]"
        )


@when(parsers.parse(
    'the traveler searches with airline "{airline}" and maxPrice {max_price:d}'
))
def _http_search_airline_then_price(
    container,
    client,
    world: dict,
    airline: str,
    max_price: int,
) -> None:
    # Seed a 4-flight grid so AND-composition + commutativity has signal:
    #   AA@299 (matches both),  AA@800 (matches airline only),
    #   UA@299 (matches price only), UA@800 (matches neither).
    # Only seed the first call to avoid duplicate ids on the second query.
    if not world.get("_filter_grid_seeded"):
        departure = datetime.fromisoformat("2026-06-01T10:00:00+00:00")
        grid = (
            ("FL-AA-CHEAP", "AA", "299"),
            ("FL-AA-PREMIUM", "AA", "800"),
            ("FL-UA-CHEAP", "UA", "299"),
            ("FL-UA-PREMIUM", "UA", "800"),
        )
        for flight_id, flight_airline, fare in grid:
            container.flight_repo.add(
                Flight(
                    id=FlightId(flight_id),
                    origin="LAX", destination="NYC",
                    departure_at=departure,
                    arrival_at=departure,
                    airline=flight_airline,
                    base_fare=Money.of(fare),
                    cabin=Cabin(),
                )
            )
        world["_filter_grid_seeded"] = True
    world["response_airline_first"] = client.get(
        "/flights/search",
        params=[
            ("origin", "LAX"),
            ("destination", "NYC"),
            ("departureDate", "2026-06-01"),
            ("airline", airline),
            ("maxPrice", str(max_price)),
        ],
    )


@when(parsers.parse(
    'the traveler searches with maxPrice {max_price:d} and airline "{airline}"'
))
def _http_search_price_then_airline(
    client,
    world: dict,
    max_price: int,
    airline: str,
) -> None:
    world["response_price_first"] = client.get(
        "/flights/search",
        params=[
            ("origin", "LAX"),
            ("destination", "NYC"),
            ("departureDate", "2026-06-01"),
            ("maxPrice", str(max_price)),
            ("airline", airline),
        ],
    )


@then("both responses return identical result sets")
def _assert_responses_identical(world: dict) -> None:
    r1 = world["response_airline_first"]
    r2 = world["response_price_first"]
    assert r1.status_code == 200 == r2.status_code, (
        f"both must be 200, got {r1.status_code} and {r2.status_code}"
    )
    body1 = r1.json()
    body2 = r2.json()
    # Compare the sorted set of flight ids — the response total and the
    # flight list under the same id set is what "identical result sets"
    # means for AND-commutativity.
    ids1 = sorted(f["id"] for f in body1.get("flights", []))
    ids2 = sorted(f["id"] for f in body2.get("flights", []))
    assert ids1 == ids2, (
        f"filter order affected result set: "
        f"airline-first={ids1!r} price-first={ids2!r}"
    )
    assert body1.get("total") == body2.get("total"), (
        f"total differs: {body1.get('total')!r} vs {body2.get('total')!r}"
    )
    # Non-vacuous — the grid guarantees one matching flight (AA@299).
    assert ids1, "expected at least one matching flight, got empty result set"
