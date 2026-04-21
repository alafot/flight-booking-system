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
}


def _error_status_for(error_code: str | None) -> int:
    if error_code is None:
        return 400
    return _COMMIT_ERROR_HTTP_STATUS.get(error_code, 400)


def _serialize_quote(quote: Quote) -> dict:
    """Quote response payload for the HTTP wire (camelCase per API contract).

    Decimals are serialised as strings to preserve precision over JSON and
    keep the response independent of downstream float conversions.
    """
    breakdown = quote.price_breakdown
    return {
        "quoteId": quote.id.value,
        "sessionId": quote.session_id.value,
        "flightId": quote.flight_id.value,
        "seatIds": [s.value for s in quote.seat_ids],
        "passengers": quote.passengers,
        "total": str(breakdown.total.amount),
        "currency": breakdown.total.currency,
        "baseFare": str(breakdown.base_fare.amount),
        "demandMultiplier": str(breakdown.demand_multiplier),
        "timeMultiplier": str(breakdown.time_multiplier),
        "dayMultiplier": str(breakdown.day_multiplier),
        "createdAt": quote.created_at.isoformat(),
        "expiresAt": quote.expires_at.isoformat(),
    }


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
    def get_seats(request: Request, flight_id: str) -> dict:
        c = _container(request)
        entries = c.seat_map_service.view(FlightId(flight_id))
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

    @app.post("/seat-locks")
    def post_seat_lock() -> dict:  # pragma: no cover — RED scaffold
        raise HTTPException(
            status_code=501, detail="seat locks not yet implemented — Phase 07"
        )

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

        commit_request = CommitRequest(
            flight_id=flight_id,
            seat_ids=(seat_id,),
            passengers=(PassengerDetails(full_name=passenger_name),),
            payment_token=payment_token,
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
