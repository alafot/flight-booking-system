"""MockPaymentGateway — unit tests.

Port-to-port: ``charge`` is the public port; result is the observable outcome.
"""

from __future__ import annotations

import pytest

from flights.adapters.mocks.payment import MockPaymentGateway, MockPaymentResult
from flights.domain.model.money import Money


class TestMockPaymentGatewayCharge:
    def test_default_token_returns_success(self) -> None:
        gateway = MockPaymentGateway()

        result = gateway.charge(token="mock-ok", amount=Money.of("299"))

        assert result == MockPaymentResult(succeeded=True, reason=None)

    def test_default_fail_token_returns_declined(self) -> None:
        gateway = MockPaymentGateway()

        result = gateway.charge(token="fail", amount=Money.of("299"))

        assert result.succeeded is False
        assert result.reason == "declined"

    @pytest.mark.parametrize("bad_token", ["denied", "bad-card", "overlimit"])
    def test_custom_fail_on_tokens_trigger_decline(self, bad_token: str) -> None:
        gateway = MockPaymentGateway(fail_on_tokens=("denied", "bad-card", "overlimit"))

        result = gateway.charge(token=bad_token, amount=Money.of("100"))

        assert result.succeeded is False
        assert result.reason == "declined"

    def test_token_not_in_fail_list_still_succeeds_with_custom_config(self) -> None:
        gateway = MockPaymentGateway(fail_on_tokens=("denied",))

        result = gateway.charge(token="mock-ok", amount=Money.of("100"))

        assert result.succeeded is True
        assert result.reason is None
