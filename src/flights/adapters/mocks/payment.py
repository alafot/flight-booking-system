"""MockPaymentGateway.

In-process payment double. Default configuration: ``token='fail'`` declines;
any other token succeeds. ``fail_on_tokens`` lets tests configure additional
decline tokens without subclassing.
"""

from __future__ import annotations

from dataclasses import dataclass

from flights.domain.model.money import Money


@dataclass(frozen=True, slots=True)
class MockPaymentResult:
    succeeded: bool
    reason: str | None = None


class MockPaymentGateway:
    """Returns SUCCESS by default; tokens in ``fail_on_tokens`` return declined."""

    def __init__(self, *, fail_on_tokens: tuple[str, ...] = ("fail",)) -> None:
        self._fail_on_tokens = fail_on_tokens

    def charge(self, token: str, amount: Money) -> MockPaymentResult:
        if token in self._fail_on_tokens:
            return MockPaymentResult(succeeded=False, reason="declined")
        return MockPaymentResult(succeeded=True, reason=None)
