"""Integration tests for the locked-in ``POST /quotes`` response contract.

Step 05-03 pins the full price-breakdown JSON shape so downstream consumers
can trust:

  * Every monetary value is a JSON string with exactly two decimal places
    (no scientific notation, no implicit float conversion).
  * Parsing any money string back through ``Decimal`` yields the same
    quantized value (precision round-trip).
  * The total is arithmetically reconstructible on paper from the other
    response fields using the Appendix B rounding rule.
  * Multipliers preserve trailing zeros ("1.00", not "1") so the display
    contract is unambiguous.

Tests drive through the real ``POST /quotes`` route against a seeded
container — ADR-003 forbids ``float`` in the domain, so these assertions
are the wire-level gate that keeps the float ban enforced end-to-end.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.adapters.http.schemas import QuoteResponse
from flights.composition.wire import Container, build_test_container
from flights.domain.model.flight import Cabin, Flight
from flights.domain.model.ids import FlightId, SeatId
from flights.domain.model.money import Money
from flights.domain.model.quote import PriceBreakdown, SeatSurchargeLine
from flights.domain.model.seat import Seat, SeatClass, SeatKind, SeatStatus


# The four top-level money fields in the response payload. Seat-surcharge
# amounts carry the same contract but live in a nested list.
_MONEY_FIELDS: tuple[str, ...] = ("baseFare", "taxes", "fees", "total")
_MULTIPLIER_FIELDS: tuple[str, ...] = (
    "demandMultiplier",
    "timeMultiplier",
    "dayMultiplier",
)
_TWO_DECIMAL_PATTERN: re.Pattern[str] = re.compile(r"^-?\d+\.\d{2}$")


def _cabin_with_quote_seat(quote_seat_id: str, *, size: int = 100) -> Cabin:
    """Build a fully AVAILABLE Economy cabin whose quoted seat is STANDARD.

    A STANDARD seat has zero surcharge, so the response's seat_surcharges
    list is empty — we still assert the response round-trips, which proves
    the shape contract holds even in the "no surcharge" branch.
    """
    cabin = Cabin()
    cabin.seats[SeatId(quote_seat_id)] = Seat(
        id=SeatId(quote_seat_id),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.STANDARD,
        status=SeatStatus.AVAILABLE,
    )
    for i in range(1, size):
        seat_id = SeatId(f"FILL-{i:03d}")
        cabin.seats[seat_id] = Seat(
            id=seat_id,
            seat_class=SeatClass.ECONOMY,
            kind=SeatKind.STANDARD,
            status=SeatStatus.AVAILABLE,
        )
    return cabin


def _cabin_with_exit_row_surcharge_seat(surcharge_seat_id: str) -> Cabin:
    """Build a cabin whose quoted seat is an EXIT_ROW (+35 USD Appendix A).

    Used by the arithmetic-reconstruction test to exercise the
    seat_surcharges branch end-to-end — the reconstruction must sum the
    surcharge into the total, matching ``PriceBreakdown.total``.
    """
    cabin = _cabin_with_quote_seat(surcharge_seat_id)
    cabin.seats[SeatId(surcharge_seat_id)] = Seat(
        id=SeatId(surcharge_seat_id),
        seat_class=SeatClass.ECONOMY,
        kind=SeatKind.EXIT_ROW,
        status=SeatStatus.AVAILABLE,
    )
    return cabin


def _seed_tuesday_empty_flight(
    container: Container,
    *,
    flight_id: str = "FL-BREAKDOWN",
    cabin: Cabin | None = None,
    fare: str = "299",
) -> None:
    """Appendix B example 1 context: Tuesday departure 30 days out, 0%
    occupancy, 299 USD fare. The time/day/demand multipliers (0.90 / 0.85
    / 1.00) combine with the WS-style example so the tests' expected math
    reproduces Appendix B line for line.
    """
    flight = Flight(
        id=FlightId(flight_id),
        origin="LAX",
        destination="NYC",
        departure_at=datetime(2026, 6, 2, 8, 0, tzinfo=UTC),  # Tuesday
        arrival_at=datetime(2026, 6, 2, 13, 0, tzinfo=UTC),
        airline="MOCK",
        base_fare=Money.of(fare),
        cabin=cabin if cabin is not None else _cabin_with_quote_seat("12C"),
    )
    container.flight_repo.add(flight)


@pytest.fixture
def breakdown_client() -> TestClient:
    """Client bound to a container seeded with the Appendix B example 1
    flight — empty Tuesday flight, 30 days out, STANDARD seat (no surcharge).
    """
    now = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
    container = build_test_container(
        now=now, audit_path=None, deterministic_ids=True
    )
    _seed_tuesday_empty_flight(container)
    return TestClient(create_app(container=container))


@pytest.fixture
def breakdown_client_with_surcharge() -> TestClient:
    """Same context as ``breakdown_client`` but the quoted seat is EXIT_ROW
    so the response carries a non-empty seat_surcharges list — exercises
    the surcharge branch of the arithmetic-reconstruction assertion.
    """
    now = datetime(2026, 5, 3, 10, 0, tzinfo=UTC)
    container = build_test_container(
        now=now, audit_path=None, deterministic_ids=True
    )
    _seed_tuesday_empty_flight(
        container,
        flight_id="FL-BREAKDOWN-EXIT",
        cabin=_cabin_with_exit_row_surcharge_seat("14A"),
    )
    return TestClient(create_app(container=container))


def _quote_appendix_b_example_1(client: TestClient) -> dict:
    response = client.post(
        "/quotes",
        json={
            "flightId": "FL-BREAKDOWN",
            "seatIds": ["12C"],
            "passengers": 1,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _quote_exit_row_surcharge(client: TestClient) -> dict:
    response = client.post(
        "/quotes",
        json={
            "flightId": "FL-BREAKDOWN-EXIT",
            "seatIds": ["14A"],
            "passengers": 1,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestQuoteResponseShape:
    """AC1: the response body exposes every locked-in field and validates
    against the Pydantic ``QuoteResponse`` contract."""

    def test_response_shape_includes_all_breakdown_fields(
        self, breakdown_client: TestClient
    ) -> None:
        body = _quote_appendix_b_example_1(breakdown_client)
        expected_fields: tuple[str, ...] = (
            "quoteId",
            "sessionId",
            "flightId",
            "seatIds",
            "passengers",
            "baseFare",
            "demandMultiplier",
            "timeMultiplier",
            "dayMultiplier",
            "seatSurcharges",
            "taxes",
            "fees",
            "total",
            "currency",
            "expiresAt",
            "createdAt",
        )
        missing = [field for field in expected_fields if field not in body]
        assert not missing, f"response missing fields: {missing!r} in {body!r}"
        # Types at the wire are stable: seatIds is an array of strings, passengers
        # is an int, surcharges is a list. Callers rely on this.
        assert isinstance(body["seatIds"], list)
        assert all(isinstance(s, str) for s in body["seatIds"])
        assert isinstance(body["passengers"], int)
        assert isinstance(body["seatSurcharges"], list)

    def test_response_validates_against_quote_response_pydantic_contract(
        self, breakdown_client: TestClient
    ) -> None:
        """Validating the live response through the ``QuoteResponse`` model
        is the structural lock-in: any drift (renamed field, wrong type,
        lost trailing zero) raises ``ValidationError`` at parse time. This
        is the guard that prevents the wire shape from silently diverging
        in future slices.
        """
        body = _quote_appendix_b_example_1(breakdown_client)
        parsed = QuoteResponse.model_validate(body)
        # Re-serialising through the model must yield an identical payload
        # — round-trip proof that the model is faithful to the JSON shape.
        assert parsed.model_dump(by_alias=True) == body


class TestQuoteResponseMoneyFormatting:
    """AC2: every money value is a 2dp string, no floats, no sci-notation."""

    @pytest.mark.parametrize("field", _MONEY_FIELDS)
    def test_money_values_are_two_decimal_strings_no_float_artifacts(
        self, breakdown_client: TestClient, field: str
    ) -> None:
        body = _quote_appendix_b_example_1(breakdown_client)
        value = body[field]
        # JSON strings, not JSON numbers — a JSON number decodes to int|float
        # and loses Decimal fidelity at the parse boundary.
        assert isinstance(value, str), (
            f"{field!r} must be a string, got {type(value).__name__}: {value!r}"
        )
        assert _TWO_DECIMAL_PATTERN.fullmatch(value), (
            f"{field!r} = {value!r} does not match NN.DD 2dp format"
        )
        assert "e" not in value.lower(), (
            f"{field!r} must not use scientific notation: {value!r}"
        )

    def test_seat_surcharge_amounts_are_two_decimal_strings(
        self, breakdown_client_with_surcharge: TestClient
    ) -> None:
        body = _quote_exit_row_surcharge(breakdown_client_with_surcharge)
        lines = body["seatSurcharges"]
        assert len(lines) == 1, f"expected one surcharge line, got {lines!r}"
        amount = lines[0]["amount"]
        assert isinstance(amount, str) and _TWO_DECIMAL_PATTERN.fullmatch(amount), (
            f"seat surcharge amount must be 2dp string, got {amount!r}"
        )


class TestQuoteResponseMoneyRoundTrip:
    """AC3: parsing any money string back via Decimal yields the same value."""

    def test_money_values_round_trip_through_decimal(
        self, breakdown_client: TestClient
    ) -> None:
        body = _quote_appendix_b_example_1(breakdown_client)
        for field in _MONEY_FIELDS:
            value = body[field]
            parsed = Decimal(value)
            # ``str(Decimal("229.00"))`` yields ``'229.00'`` only when the
            # Decimal has an explicit 2dp exponent. If the wire serializer
            # used ``float(...)`` anywhere, trailing zeros would drop and
            # this equality would fail.
            assert str(parsed) == value, (
                f"{field!r} round-trip mismatch: "
                f"str(Decimal({value!r})) = {str(parsed)!r}"
            )


class TestQuoteTotalReproducibleOnPaper:
    """AC4/AC5: total equals the arithmetic of the response's own fields.

    The domain holds taxes at full precision (Appendix B keeps the raw
    product so banker's rounding is applied once at the end). The wire
    displays taxes quantized to 2dp. Reconstructing from the wire values
    therefore lands at most one cent away from the wire total — that
    single-cent band is the honest expression of "reproducible on paper"
    under the Appendix B rule. A gap wider than one cent means the total
    is NOT derivable from the displayed components.
    """

    @staticmethod
    def _reconstruct(body: dict) -> Money:
        return PriceBreakdown(
            base_fare=Money.of(body["baseFare"]),
            demand_multiplier=Decimal(body["demandMultiplier"]),
            time_multiplier=Decimal(body["timeMultiplier"]),
            day_multiplier=Decimal(body["dayMultiplier"]),
            seat_surcharges=tuple(
                SeatSurchargeLine(
                    seat=SeatId(line["seat"]), amount=Money.of(line["amount"])
                )
                for line in body["seatSurcharges"]
            ),
            taxes=Money.of(body["taxes"]),
            fees=Money.of(body["fees"]),
        ).total

    def test_total_reproduces_from_response_fields_arithmetic(
        self, breakdown_client: TestClient
    ) -> None:
        body = _quote_appendix_b_example_1(breakdown_client)
        expected_total = self._reconstruct(body)
        actual_total = Money.of(body["total"])
        # One-cent tolerance reflects the cent-boundary rounding gap
        # between the full-precision domain total and the 2dp displayed
        # components. A tolerance greater than 0.01 USD would indicate
        # a genuine arithmetic bug.
        delta = abs(actual_total.amount - expected_total.amount)
        assert delta <= Decimal("0.01"), (
            f"wire total {body['total']} does not reproduce from displayed "
            f"components (reconstruction: {expected_total.amount}, "
            f"delta: {delta})"
        )

    def test_total_reproduces_with_seat_surcharge(
        self, breakdown_client_with_surcharge: TestClient
    ) -> None:
        body = _quote_exit_row_surcharge(breakdown_client_with_surcharge)
        expected_total = self._reconstruct(body)
        actual_total = Money.of(body["total"])
        # Same one-cent tolerance; the EXIT_ROW surcharge (+35.00) is
        # added at 2dp precision so it contributes exactly, meaning the
        # gap still comes only from the tax component's fractional tail.
        delta = abs(actual_total.amount - expected_total.amount)
        assert delta <= Decimal("0.01"), (
            f"wire total {body['total']} does not reproduce from displayed "
            f"components (reconstruction: {expected_total.amount}, "
            f"delta: {delta})"
        )


class TestQuoteResponseMultiplierFormatting:
    """AC7: multipliers are strings preserving trailing zeros ("1.00", "0.90")."""

    @pytest.mark.parametrize("field", _MULTIPLIER_FIELDS)
    def test_multipliers_are_strings_preserving_trailing_zeros(
        self, breakdown_client: TestClient, field: str
    ) -> None:
        body = _quote_appendix_b_example_1(breakdown_client)
        value = body[field]
        assert isinstance(value, str), (
            f"{field!r} must be a string, got {type(value).__name__}: {value!r}"
        )
        # The pricing rule tables express multipliers at 2dp ("1.00", "0.90",
        # "0.85"). Round-tripping through ``Decimal`` must preserve that
        # trailing zero so consumers can display the receipt unambiguously.
        parsed = Decimal(value)
        assert str(parsed) == value, (
            f"{field!r}: trailing zeros lost on round-trip "
            f"(str(Decimal({value!r})) = {str(parsed)!r})"
        )
        # The Appendix B fixtures for this flight — assertions that would
        # fail if FastAPI/Pydantic coerced the string through a float.
        expected = {
            "demandMultiplier": "1.00",
            "timeMultiplier": "0.90",
            "dayMultiplier": "0.85",
        }[field]
        assert value == expected, f"{field!r}: expected {expected!r}, got {value!r}"
