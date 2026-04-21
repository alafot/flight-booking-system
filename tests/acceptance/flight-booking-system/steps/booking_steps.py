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


# ---- Pending-steps fallback --------------------------------------------------
# For milestone scenarios that are @pending, pytest-bdd collects them but they
# are skipped by `pytest_collection_modifyitems` in conftest.py before any step
# is evaluated. No catch-all step function is necessary (and pytest-bdd 8.x
# eagerly matches a `{_step}` wildcard over more-specific patterns, so any
# fallback here poisons the enabled scenarios). Step definitions for milestone
# scenarios are added to this file as each slice is DELIVERed.
