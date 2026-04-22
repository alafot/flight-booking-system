# flight-booking-system — Running the Tests

Python 3.12 backend. All test tooling is declared in `pyproject.toml` under the `dev` extra.

## 1. Setup

From the project root:

```bash
# Create and activate a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install the project in editable mode with the dev extras
pip install -e '.[dev]'
```

The `dev` extra pulls in `pytest`, `pytest-bdd`, `httpx`, `hypothesis`, `ruff`, and `mypy`.

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

Custom markers are registered in `pyproject.toml` (`walking_skeleton`, `real_io`, `in_memory`, `adapter_integration`, `pending`, `requires_external`, `driving_adapter`, `kpi`).

Scenarios tagged `@pending` are auto-skipped; DELIVER removes the tag to enable one at a time.

## 3. Running tests

### Everything

```bash
pytest
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
pytest -m walking_skeleton          # the single thin-slice smoke test
pytest -m kpi                       # outcome-KPI scenarios
pytest -m "not pending"             # skip scaffolded-but-not-enabled scenarios
pytest -m adapter_integration       # driven-adapter integration tests
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

### Useful flags

```bash
pytest -x                 # stop on first failure
pytest -vv               # verbose test names
pytest -q                 # quiet summary
pytest --lf              # re-run last failures only
pytest -n auto            # parallel (requires pytest-xdist, not installed by default)
```

## 4. Concurrency harness (KPI-T2)

The race-last-seat harness verifies that 100 trials of 10 concurrent clients each produce exactly one winner. It can be run as a script or via pytest:

```bash
# Script form — prints a JSON summary, exits 1 on any double-booking
python scripts/race_last_seat.py
python scripts/race_last_seat.py --trials 50

# Test form
pytest tests/e2e/test_race_last_seat.py
```

## 5. Property-based tests

`tests/unit/domain/test_pricing_properties.py` uses Hypothesis. Examples are cached under `.hypothesis/` — safe to delete to force regeneration.

## 6. Load tests (KPI-P1/P2/P3)

Load tests are driven by Locust (not in the default dev extras — install ad-hoc):

```bash
pip install locust
locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 1m
```

## 7. Lint and type-check

```bash
ruff check .
ruff format --check .
mypy src tests
```

## 8. Troubleshooting

- **`ModuleNotFoundError: flights`** — the project wasn't installed editable. Run `pip install -e '.[dev]'` inside the active venv.
- **Acceptance tests all skipped** — most scenarios are `@pending` until DELIVER enables them. Use `pytest -m "not pending" tests/acceptance` to see only the active ones.
- **Stale Hypothesis DB causing flakes** — `rm -rf .hypothesis`.
