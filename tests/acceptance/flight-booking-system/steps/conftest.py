"""pytest-bdd fixtures for flight-booking-system acceptance tests.

Scaffolded by DISTILL. Fixtures wire a test container whose services raise
AssertionError until DELIVER replaces the scaffolds. Scenarios tagged @pending
are skipped automatically — DELIVER enables them one at a time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flights.adapters.http.app import create_app
from flights.adapters.mocks.clock import FrozenClock
from flights.composition.wire import Container, build_test_container


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pending scenarios automatically. DELIVER removes the tag to enable one."""
    skip_pending = pytest.mark.skip(reason="scenario tagged @pending — DELIVER will enable")
    for item in items:
        if "pending" in {m.name for m in item.iter_markers()}:
            item.add_marker(skip_pending)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC))


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def container(frozen_clock: FrozenClock, audit_path: Path) -> Container:
    """Test container wired with FrozenClock + InMemory stores + deterministic ids.

    Note: ``build_test_container`` is a RED scaffold — until DELIVER implements it,
    this fixture itself will raise AssertionError, which is the desired outcome for
    tests that depend on the container being wired.
    """
    return build_test_container(now=frozen_clock.now(), audit_path=None, deterministic_ids=True)


@pytest.fixture
def client(container: Container) -> TestClient:
    """HTTP driving adapter for acceptance tests."""
    app = create_app(container=container)
    return TestClient(app)


@pytest.fixture
def world() -> dict:
    """Shared state bag between pytest-bdd Given/When/Then steps."""
    return {}
