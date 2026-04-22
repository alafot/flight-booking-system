"""HTTP request/response schemas for the FastAPI driving adapter.

Pydantic v2 per ADR-002. Keep schemas focused on the HTTP boundary — no domain
types here — so ``app.py`` stays a thin routing layer.

The ``SearchQueryParams`` model validates every query parameter for the search
endpoint and clamps ``size`` at 20 (ADR says clamp, not 400). Validation
failures raise ``RequestValidationError`` which the app translates to HTTP 400
with a per-field error list.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, Field, field_validator

from flights.domain.model.seat import SeatClass

MAX_PAGE_SIZE: int = 20
MAX_PASSENGERS: int = 9
MIN_PASSENGERS: int = 1
MAX_SEATS_PER_QUOTE: int = 9  # mirrors passengers cap; ADR-006 keeps the two aligned
IATA_PATTERN: str = r"^[A-Z]{3}$"


class SeatSurchargeResponse(BaseModel):
    """Single seat-surcharge line on the wire.

    ``amount`` is kept as a string so ``Decimal`` precision round-trips —
    a ``float`` field here would drop the trailing zero on values like
    ``"35.00"`` and violate ADR-003's "no float" rule at the HTTP boundary.
    """

    seat: str
    amount: str

    model_config = {"populate_by_name": True}


class QuoteResponse(BaseModel):
    """Locked-in ``POST /quotes`` response contract (step 05-03).

    Every monetary field and every multiplier is typed as ``str`` rather
    than ``Decimal`` or ``float``: the contract is that values are sent
    on the wire as JSON strings produced by ``str(Decimal(...))`` so
    consumers can parse them back via ``Decimal(...)`` without precision
    loss. Using Pydantic's built-in ``Decimal`` type would serialise as
    a JSON number and re-enable the float round-trip problem the step
    is specifically closing.

    The model exists primarily as a structural guard: the route builds a
    ``QuoteResponse`` and FastAPI serialises through it, which means any
    future drift (renamed field, wrong type, forgotten trailing zero)
    raises ``ValidationError`` at construction time — the wire shape
    cannot silently change without a failing test.
    """

    quoteId: str
    sessionId: str
    flightId: str
    seatIds: list[str]
    passengers: int
    baseFare: str
    demandMultiplier: str
    timeMultiplier: str
    dayMultiplier: str
    seatSurcharges: list[SeatSurchargeResponse]
    taxes: str
    fees: str
    total: str
    currency: str
    expiresAt: str
    createdAt: str

    model_config = {"populate_by_name": True}


class BookingRequestBody(BaseModel):
    """Validated body for ``POST /bookings`` (step 06-03).

    ``quoteId`` is optional per ADR-006: when present, ``BookingService``
    looks up the quote and charges its locked-in total (KPI-T1). When
    absent, the walking-skeleton path charges ``flight.base_fare`` — kept
    explicitly for backward compatibility with the step-01-03 WS clients.

    The schema is declared here as the canonical wire contract; the
    current ``app.py`` still accepts a loose ``dict`` payload so existing
    integration tests keep working. A follow-up slice will route the
    endpoint through this model once every integration test migrates.
    """

    flight_id: Annotated[str, Field(alias="flightId", min_length=1)]
    seat_id: Annotated[str, Field(alias="seatId", min_length=1)]
    passenger: dict  # {"name": "..."} — tightened in a later slice
    payment_token: Annotated[str, Field(alias="paymentToken", min_length=1)]
    quote_id: Annotated[str | None, Field(alias="quoteId", default=None)] = None
    # Step 07-02: ``lockId``/``sessionId`` are optional companions to
    # ``quoteId`` — all three travel together under ADR-008's "quote a
    # price, lock the seat, commit the booking" sequence. Absent for the
    # milestone-06 and walking-skeleton paths where commits proceed
    # without a seat lock.
    lock_id: Annotated[str | None, Field(alias="lockId", default=None)] = None
    session_id: Annotated[str | None, Field(alias="sessionId", default=None)] = None

    model_config = {"populate_by_name": True}


class SeatLockRequestBody(BaseModel):
    """Validated body for ``POST /seat-locks`` (step 07-01).

    camelCase on the wire (``flightId``/``seatIds``/``sessionId``); snake_case
    inside. ``seatIds`` is capped at ``MAX_SEATS_PER_QUOTE`` mirroring the
    quote contract — a seat-lock can cover multiple seats in one atomic
    acquire, but the cap prevents a pathological single-request lock of an
    entire cabin.
    """

    flight_id: Annotated[str, Field(alias="flightId", min_length=1)]
    seat_ids: Annotated[
        list[str],
        Field(alias="seatIds", min_length=1, max_length=MAX_SEATS_PER_QUOTE),
    ]
    session_id: Annotated[str, Field(alias="sessionId", min_length=1)]

    model_config = {"populate_by_name": True}


class SeatLockResponse(BaseModel):
    """Structural guard for the ``POST /seat-locks`` 201 body (step 07-01).

    ``expiresAt`` is an ISO-8601 string so the client parses it with the
    same ``datetime.fromisoformat`` that the acceptance Then step uses.
    """

    lockId: str
    expiresAt: str

    model_config = {"populate_by_name": True}


class QuoteRequestBody(BaseModel):
    """Validated body for ``POST /quotes`` (ADR-002 + ADR-006).

    The HTTP wire shape is camelCase per the API contract; inside the app we
    keep snake_case attributes because the application service takes a
    ``QuoteRequest`` that uses snake_case. Pydantic's ``alias`` handles the
    translation — clients send ``flightId`` / ``seatIds`` / ``passengers``.

    Session id is optional at this phase: if omitted, the service mints one
    and echoes it back on the response. Phase 06 will enforce session-binding
    on commit; for now it's a pass-through identifier.
    """

    flight_id: Annotated[str, Field(alias="flightId", min_length=1)]
    seat_ids: Annotated[
        list[str],
        Field(alias="seatIds", min_length=1, max_length=MAX_SEATS_PER_QUOTE),
    ]
    passengers: Annotated[int, Field(ge=MIN_PASSENGERS, le=MAX_PASSENGERS)]
    session_id: Annotated[str | None, Field(alias="sessionId", default=None)] = None

    model_config = {"populate_by_name": True}


class SearchQueryParams(BaseModel):
    """Validated query parameters for ``GET /flights/search``.

    ``class`` is a Python keyword, so we alias the field to ``class_`` while
    accepting ``class`` on the wire. FastAPI binds each attribute to a
    query-string parameter via the ``Query`` dependency in ``app.py``.

    ``return_date`` (camelCase ``returnDate`` on the wire) is optional;
    when present the endpoint switches to the round-trip response shape
    (``pairs``/``pairCount``/``flightCount``) per ADR-007. When absent
    the legacy one-way shape is preserved for backwards compatibility.
    """

    origin: Annotated[
        str, Field(min_length=3, max_length=3, pattern=IATA_PATTERN)
    ]
    destination: Annotated[
        str, Field(min_length=3, max_length=3, pattern=IATA_PATTERN)
    ]
    departure_date: date_type
    return_date: date_type | None = None
    passengers: Annotated[
        int, Field(ge=MIN_PASSENGERS, le=MAX_PASSENGERS)
    ] = 1
    seat_class: SeatClass | None = None
    page: Annotated[int, Field(ge=1)] = 1
    size: Annotated[int, Field(ge=1)] = MAX_PAGE_SIZE

    @field_validator("size", mode="after")
    @classmethod
    def _clamp_size_to_maximum(cls, value: int) -> int:
        # Clamp rather than reject — ADR calls this a soft cap for DoS protection.
        return min(value, MAX_PAGE_SIZE)


def search_query_params(
    origin: Annotated[str, Query(min_length=3, max_length=3, pattern=IATA_PATTERN)],
    destination: Annotated[
        str, Query(min_length=3, max_length=3, pattern=IATA_PATTERN)
    ],
    departureDate: Annotated[date_type, Query()],  # noqa: N803 — camelCase at wire
    returnDate: Annotated[date_type | None, Query()] = None,  # noqa: N803
    passengers: Annotated[int, Query(ge=MIN_PASSENGERS, le=MAX_PASSENGERS)] = 1,
    # ``class`` is reserved; accept it on the wire via alias.
    class_: Annotated[SeatClass | None, Query(alias="class")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1)] = MAX_PAGE_SIZE,
) -> SearchQueryParams:
    """Assemble a validated ``SearchQueryParams`` from the request query string.

    Delegating validation to FastAPI's ``Query`` annotations lets us map HTTP
    parameter names (``departureDate``, ``class``) to snake_case model fields
    in one place. FastAPI raises ``RequestValidationError`` before this body
    runs if any constraint fails; the app.py exception handler converts those
    to HTTP 400.
    """
    return SearchQueryParams(
        origin=origin,
        destination=destination,
        departure_date=departureDate,
        return_date=returnDate,
        passengers=passengers,
        seat_class=class_,
        page=page,
        size=size,
    )


class RoundTripPairResponse(BaseModel):
    """Single round-trip pair on the wire (step 08-01).

    ``outbound`` and ``return`` are the two flight payloads serialized by
    the route handler's ``_serialize_flight`` helper. They are typed
    loosely as dict because the route builds them via that helper rather
    than through a Pydantic model — keeping this schema a thin contract
    guard rather than a second source of truth for the flight wire shape.

    ``totalIndicativePrice`` is a string-encoded Decimal, mirroring the
    quote contract (ADR-003: no float at the HTTP boundary).
    """

    outbound: dict
    return_: Annotated[dict, Field(alias="return")]
    totalIndicativePrice: str

    model_config = {"populate_by_name": True}


class RoundTripResponse(BaseModel):
    """Pageable round-trip envelope (step 08-01).

    Both ``pairCount`` (the total number of eligible pairs across the
    whole result set) and ``flightCount`` (= 2 × pairCount) are pinned
    here so clients don't recompute the redundant total themselves.
    """

    pairs: list[RoundTripPairResponse]
    page: int
    size: int
    pairCount: int
    flightCount: int

    model_config = {"populate_by_name": True}
