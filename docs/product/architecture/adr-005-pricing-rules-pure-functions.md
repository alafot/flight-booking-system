# ADR-005 — Pricing & rule engines as pure functions

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

The trust contract (KPI-T1 quote fidelity, KPI-T3 audit replay) is easiest to prove when price and rule evaluation have zero hidden state. Slice 04 AC2 explicitly requires property-based testability over 1000+ inputs. Rule windows (cancellation fees, advance booking, capacity ceiling) must be boundary-tested.

## Decision

- `domain/pricing.py` exposes **`price(base, occupancy_pct, days_before, dow, surcharges, taxes, fees) → PriceBreakdown`** as a pure function.
- `domain/rules.py` exposes boundary-tested pure functions: `can_book(flight, now)`, `cancellation_fee_percent(now, departure)`, `advance_booking_ok(now, departure)`, `capacity_ok(flight)`, etc.
- **Multiplier tables are module-level constants** (`DEMAND_TABLE`, `TIME_TABLE`, `DOW_TABLE`), each a sorted list of `(threshold, multiplier)` tuples. One authoritative location per Appendix B section.
- Boundary policy: **left-inclusive, right-exclusive** (`[0%, 31%)`, `[31%, 51%)`, etc.). Documented in module docstring; boundary tests assert both sides of each cutoff.

## Alternatives considered

| Alt | Why rejected |
|---|---|
| OOP pricing class with injected tables | Same behavior, more ceremony; no test wins — the "stateful" class is still stateless. |
| Rule engine via a third-party library (e.g., `business_rules`) | Overkill for ~8 rules; adds a dependency and an abstraction layer. |
| Inline rule checks in services | Spreads business rules across layers; fails "rule table in one place" AC from slice 04 and slice 11. |

## Consequences

- **+** Trivial PBT: hypothesis generates (`base`, `occupancy`, `days`, `dow`) and asserts invariants (monotonicity per dimension where appropriate, positivity, determinism).
- **+** Audit replay is `price(**audit_entry.inputs) == audit_entry.total` — one line.
- **+** Adding a business rule means adding one function + one test — no cross-layer changes.
- **−** Developers must not sneak `datetime.now()` into `pricing.py` or `rules.py`. Enforced by:
  - Code review checklist: "no clock, no I/O, no randomness in `domain/pricing.py` or `domain/rules.py`".
  - A lint rule (grep-based pre-commit hook) that forbids `datetime`, `random`, `time`, `logging` imports in those files.

## Related

ADR-001 (OOP + pure domain core), ADR-003 (Decimal money), ADR-006 (audit log replay).
