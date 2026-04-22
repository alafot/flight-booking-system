"""FastAPI app factory.

Driving adapter per ADR-002. Implements the walking-skeleton routes:
``GET /flights/search``, ``POST /bookings``, ``GET /bookings/{reference}``.
Seat-map, quote and seat-lock endpoints remain scaffolds until their
dedicated slices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from flights.adapters.http.schemas import (
    QuoteRequestBody,
    QuoteResponse,
    SeatLockRequestBody,
    SeatLockResponse,
    SeatSurchargeResponse,
    SearchQueryParams,
    search_query_params,
)
from flights.application.booking_service import CommitRequest
from flights.application.quote_service import (
    FlightAlreadyDeparted,
    QuoteNotFound,
    QuoteRequest,
)
from flights.application.search_service import SearchRequest
from flights.domain.model.booking import Booking
from flights.domain.model.ids import BookingReference, FlightId, SeatId, SessionId
from flights.domain.model.money import Money
from flights.domain.model.passenger import PassengerDetails
from flights.domain.model.quote import Quote

if TYPE_CHECKING:
    from flights.composition.wire import Container


def _container(request: Request) -> Container:
    container: Container | None = request.app.state.container
    if container is None:
        raise HTTPException(status_code=500, detail="container not wired")
    return container


# Map internal Python field names back to the names the HTTP client sent.
# FastAPI reports the query parameter name in ``loc`` (e.g. ``("query", "departureDate")``
# for the route dependency), but the nested ``SearchQueryParams`` validator
# reports the model attribute (e.g. ``departure_date``). Normalise both.
_FIELD_NAME_ON_WIRE: dict[str, str] = {
    "departure_date": "departureDate",
    "seat_class": "class",
    "class_": "class",
}


def _extract_field_name(loc: tuple[Any, ...] | list[Any]) -> str:
    # ``loc`` is a path like ``("query", "origin")`` or ``("body", "departure_date")``.
    # The last segment identifies the offending field.
    if not loc:
        return ""
    last = str(loc[-1])
    return _FIELD_NAME_ON_WIRE.get(last, last)


def _serialize_flight(flight: Any) -> dict:
    return {
        "id": flight.id.value,
        "flightId": flight.id.value,
        "origin": flight.origin,
        "destination": flight.destination,
        "departureAt": flight.departure_at.isoformat(),
        "arrivalAt": flight.arrival_at.isoformat(),
        "airline": flight.airline,
        "baseFare": {
            "amount": str(flight.base_fare.amount),
            "currency": flight.base_fare.currency,
        },
    }


# Map BookingService commit error codes to HTTP status codes. Anything not
# listed here falls back to 400 (bad request) — this preserves the existing
# behaviour for FLIGHT_NOT_FOUND while making the seat-validation branches
# from step 03-03 explicit.
_COMMIT_ERROR_HTTP_STATUS: dict[str, int] = {
    "UNKNOWN_SEAT": 400,
    "SEAT_ALREADY_BOOKED": 409,
    "SEAT_NOT_FOR_SALE": 409,
    "FLIGHT_NOT_FOUND": 400,
    # Phase 06-02: payment declined is a client-side financial failure —
    # RFC 7231 reserves 402 Payment Required for this case.
    "PAYMENT_DECLINED": 402,
    # Step 06-03: quote-trust branches. 410 Gone is the canonical
    # "resource was here but is no longer available" — fits a quote that
    # has crossed its 30-minute TTL. 404 is the standard "never existed".
    "QUOTE_EXPIRED": 410,
    "QUOTE_NOT_FOUND": 404,
}


def _error_status_for(error_code: str | None) -> int:
    if error_code is None:
        return 400
    return _COMMIT_ERROR_HTTP_STATUS.get(error_code, 400)


def _serialize_quote(quote: Quote) -> dict:
    """Quote response payload for the HTTP wire (camelCase per API contract).

    The ``QuoteResponse`` Pydantic model locks the shape in (step 05-03):
    every money field is a string produced via ``str(Decimal(...))`` so
    ``Decimal(value)`` round-trips exactly, matching ADR-003's "no float"
    rule at the HTTP boundary.

    ``taxes`` and ``fees`` are carried at full Decimal precision in the
    domain so ``PriceBreakdown.total`` can apply the Appendix B rounding
    rule once. At the wire we project them through ``Money.of`` to the
    cent-quantized display value — matching the receipt convention where
    consumers see line items at 2dp.
    """
    breakdown = quote.price_breakdown
    response = QuoteResponse(
        quoteId=quote.id.value,
        sessionId=quote.session_id.value,
        flightId=quote.flight_id.value,
        seatIds=[s.value for s in quote.seat_ids],
        passengers=quote.passengers,
        baseFare=str(breakdown.base_fare.amount),
        demandMultiplier=str(breakdown.demand_multiplier),
        timeMultiplier=str(breakdown.time_multiplier),
        dayMultiplier=str(breakdown.day_multiplier),
        seatSurcharges=[
            SeatSurchargeResponse(seat=line.seat.value, amount=str(line.amount.amount))
            for line in breakdown.seat_surcharges
        ],
        taxes=str(Money.of(breakdown.taxes.amount, breakdown.taxes.currency).amount),
        fees=str(Money.of(breakdown.fees.amount, breakdown.fees.currency).amount),
        total=str(breakdown.total.amount),
        currency=breakdown.total.currency,
        createdAt=quote.created_at.isoformat(),
        expiresAt=quote.expires_at.isoformat(),
    )
    return response.model_dump(by_alias=True)


def _serialize_booking(booking: Booking) -> dict:
    return {
        "bookingReference": booking.reference.value,
        "status": booking.status.value,
        "flightId": booking.flight_id.value,
        "seats": [s.value for s in booking.seat_ids],
        "passengers": [{"name": p.full_name} for p in booking.passengers],
        "totalCharged": {
            "amount": str(booking.total_charged.amount),
            "currency": booking.total_charged.currency,
        },
        "confirmedAt": booking.confirmed_at.isoformat(),
    }


def create_app(container: Container | None = None) -> FastAPI:
    """Create the FastAPI app, optionally wired to a test-built container."""
    app = FastAPI(title="Flight Booking System", version="0.0.1")
    app.state.container = container

    @app.exception_handler(RequestValidationError)
    def _validation_error_to_400(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI defaults to 422; our API contract uses 400 with a per-field list.
        errors = [
            {
                "field": _extract_field_name(err.get("loc", ())),
                "message": err.get("msg", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(status_code=400, content={"errors": errors})

    @app.get("/flights/search")
    def search_flights(
        request: Request,
        params: Annotated[SearchQueryParams, Depends(search_query_params)],
    ) -> dict:
        c = _container(request)
        result = c.search_service.search(
            SearchRequest(
                origin=params.origin,
                destination=params.destination,
                departure_date=params.departure_date.isoformat(),
                passengers=params.passengers,
                page=params.page,
                size=params.size,
            )
        )
        start = (result.page - 1) * result.size
        end = start + result.size
        page_flights = result.flights[start:end]
        return {
            "flights": [_serialize_flight(f) for f in page_flights],
            "page": result.page,
            "size": result.size,
            "total": result.total,
        }

    @app.get("/flights/{flight_id}/seats")
    def get_seats(
        request: Request, flight_id: str, sessionId: str | None = None,  # noqa: N803 — camelCase at wire
    ) -> dict:
        c = _container(request)
        requesting_session = SessionId(sessionId) if sessionId else None
        entries = c.seat_map_service.view(
            FlightId(flight_id), session_id=requesting_session,
        )
        if entries is None:
            raise HTTPException(status_code=404, detail="flight not found")
        return {
            "flightId": flight_id,
            "seats": [
                {
                    "seatId": entry.seat_id.value,
                    "class": entry.seat_class.value,
                    "kind": entry.kind.value,
                    "status": entry.status.value,
                }
                for entry in entries
            ],
        }

    @app.post("/quotes")
    def post_quote(request: Request, payload: QuoteRequestBody) -> dict:
        c = _container(request)
        quote_request = QuoteRequest(
            flight_id=FlightId(payload.flight_id),
            seat_ids=tuple(SeatId(s) for s in payload.seat_ids),
            passengers=payload.passengers,
            session_id=(
                SessionId(payload.session_id) if payload.session_id is not None else None
            ),
        )
        try:
            quote = c.quote_service.quote(quote_request)
        except QuoteNotFound as missing:
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        except FlightAlreadyDeparted as departed:
            raise HTTPException(status_code=400, detail=str(departed)) from departed
        return _serialize_quote(quote)

    @app.post("/seat-locks", status_code=201)
    def post_seat_lock(
        request: Request, payload: SeatLockRequestBody,
    ) -> JSONResponse:
        """Acquire a 10-minute seat lock for a session (step 07-01).

        201 with ``{lockId, expiresAt}`` on acquire; 409 with
        ``{detail: "seat unavailable", conflicts: [...]}`` when another
        session already holds a live lock on any requested seat.

        The 409 body is flat (``detail``/``conflicts`` at top level) so
        callers don't have to unwrap a nested FastAPI ``HTTPException.detail``
        envelope. Returning a ``JSONResponse`` directly keeps the contract
        explicit and matches the integration-test expectations.
        """
        c = _container(request)
        result = c.seat_hold_service.acquire(
            flight_id=FlightId(payload.flight_id),
            seat_ids=tuple(SeatId(s) for s in payload.seat_ids),
            session_id=SessionId(payload.session_id),
        )
        if not result.success:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "seat unavailable",
                    "conflicts": [s.value for s in result.conflicts],
                },
            )
        assert result.lock_id is not None  # success invariant
        assert result.expires_at is not None
        body = SeatLockResponse(
            lockId=result.lock_id,
            expiresAt=result.expires_at.isoformat(),
        ).model_dump(by_alias=True)
        return JSONResponse(status_code=201, content=body)

    @app.post("/bookings", status_code=201)
    def post_booking(request: Request, payload: dict) -> dict:
        c = _container(request)
        try:
            flight_id = FlightId(payload["flightId"])
            seat_id = SeatId(payload["seatId"])
            passenger_name = payload["passenger"]["name"]
            payment_token = payload["paymentToken"]
        except KeyError as missing:
            raise HTTPException(
                status_code=422, detail=f"missing field: {missing.args[0]}"
            ) from missing

        # Step 06-03: ``quoteId`` is optional. Present → BookingService
        # honors the quote's locked-in total and maps TTL/unknown-id to
        # 410/404. Absent → walking-skeleton path (charges base_fare).
        # ``BookingRequestBody`` is deliberately not a pydantic model yet
        # because the existing WS integration tests post loose dicts; we
        # tighten the schema in a later slice.
        from flights.domain.model.ids import QuoteId

        raw_quote_id = payload.get("quoteId")
        quote_id = QuoteId(raw_quote_id) if raw_quote_id is not None else None

        commit_request = CommitRequest(
            flight_id=flight_id,
            seat_ids=(seat_id,),
            passengers=(PassengerDetails(full_name=passenger_name),),
            payment_token=payment_token,
            quote_id=quote_id,
        )
        result = c.booking_service.commit(commit_request)
        if result.booking is None:
            status = _error_status_for(result.error_code)
            raise HTTPException(
                status_code=status,
                detail=result.error_message,
            )
        return _serialize_booking(result.booking)

    @app.get("/bookings/{reference}")
    def get_booking(request: Request, reference: str) -> dict:
        c = _container(request)
        booking = c.booking_service.get(BookingReference(reference))
        if booking is None:
            raise HTTPException(status_code=404, detail="booking not found")
        return _serialize_booking(booking)

    return app
