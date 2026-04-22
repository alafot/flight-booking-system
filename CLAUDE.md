# flight-booking-system — Claude Code project context

Python backend implementing the spec at `Flight-Booking-System.pdf`. Developed under nWave methodology; artifacts live in `docs/product/` (SSOT) and `docs/feature/flight-booking-system/` (feature delta).

## Development Paradigm

This project follows the **object-oriented** paradigm. Use @nw-software-crafter for implementation.

Exceptions (kept as **pure functions**):
- `domain/pricing.py` — dynamic pricing engine (Appendix B multipliers).
- `domain/rules.py` — business rule checks (cancellation windows, advance booking, capacity ceiling, etc.).

See `docs/product/architecture/adr-005-pricing-rules-pure-functions.md` for rationale.

## Architecture at a glance

Hexagonal / Ports & Adapters, modular monolith, single process.

```
HTTP (FastAPI) → Application Services → Domain (+ pure pricing/rules) → Driven Ports → Adapters (in-memory, mocks)
```

Source tree: `src/flights/{adapters,application,domain,composition}/`.
SSOT: `docs/product/architecture/brief.md` + `adr-*.md`.

## Key constraints

- Python 3.12, FastAPI, Pydantic v2, `decimal.Decimal` with `ROUND_HALF_EVEN`.
- Domain imports zero I/O modules (enforced).
- No `datetime.now()` or `float` in `domain/` — clocks and money are injected.
- In-memory persistence with `threading.RLock`. Single process, no distributed locking.
- Session-bound quotes + seat locks via `X-Session-Id` header.

## Canonical commands (once the project is implemented)

```bash
# Run the API
uvicorn flights.adapters.http.app:app --reload

# Unit + integration tests
pytest tests/unit tests/integration

# Acceptance (Gherkin)
pytest tests/acceptance

# Concurrency harness (KPI-T2)
python scripts/race_last_seat.py

# Load tests (KPI-P1/P2/P3)
locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 1m
```

## Wave status

- [x] DISCUSS — `docs/feature/flight-booking-system/discuss/`
- [x] DESIGN — `docs/product/architecture/` + `docs/feature/flight-booking-system/design/`
- [ ] DEVOPS
- [ ] DISTILL
- [ ] DELIVER
