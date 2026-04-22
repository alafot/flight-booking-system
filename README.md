# flight-booking-system

Python 3.14 backend. All tooling is declared in `pyproject.toml` under the `dev` extra.

## 1. Setup

From the project root:

```bash
make install
```

This creates a `.venv`, installs the project in editable mode with the `dev` extras (`pytest`, `pytest-bdd`, `httpx`, `hypothesis`, `ruff`, `mypy`, `pre-commit`), and registers the pre-commit hooks.

Activate the venv before running the commands below:

```bash
source .venv/bin/activate
```

## 2. Test layout

```
tests/
├── unit/           # Fast, isolated. Domain logic, adapters, composition.
├── integration/    # FastAPI TestClient flows + driven-adapter integration (e.g. JSONL audit).
├── acceptance/     # Gherkin feature files executed by pytest-bdd.
├── e2e/            # End-to-end harnesses (race-last-seat, etc.).
├── fixtures/       # Shared catalog/cabin builders.
└── support/        # Test helpers (e.g. audit replay).
```

Custom markers registered in `pyproject.toml`: `walking_skeleton`, `real_io`, `in_memory`, `adapter_integration`, `pending`, `requires_external`, `driving_adapter`, `kpi`.

## 3. Running tests

### Everything

```bash
make test
```

### By layer

```bash
pytest tests/unit
pytest tests/integration
pytest tests/acceptance
pytest tests/e2e
```

### By marker

```bash
pytest -m walking_skeleton
pytest -m kpi
pytest -m "not pending"
pytest -m adapter_integration
```

### A single file or test

```bash
pytest tests/unit/domain/test_pricing.py
pytest tests/unit/domain/test_pricing.py::test_weekend_surcharge
```

### A single Gherkin scenario

```bash
pytest tests/acceptance -k "locks the last seat"
```

## 4. Concurrency harness (KPI-T2)

The race-last-seat harness verifies that 100 trials of 10 concurrent clients each produce exactly one winner:

```bash
# Script form — prints a JSON summary, exits 1 on any double-booking
python scripts/race_last_seat.py

# Test form
pytest tests/e2e/test_race_last_seat.py
```

## 5. Property-based tests

`tests/unit/domain/test_pricing_properties.py` uses Hypothesis.

## 6. Load tests (KPI-P1/P2/P3)

```bash
pip install locust
locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 1m
```

## 7. Lint, type-check, and format

```bash
make lint       # ruff check + ruff format --check + mypy
make format     # ruff format + ruff check --fix
```
