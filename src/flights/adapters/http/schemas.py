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
    """

    origin: Annotated[
        str, Field(min_length=3, max_length=3, pattern=IATA_PATTERN)
    ]
    destination: Annotated[
        str, Field(min_length=3, max_length=3, pattern=IATA_PATTERN)
    ]
    departure_date: date_type
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
        passengers=passengers,
        seat_class=class_,
        page=page,
        size=size,
    )
