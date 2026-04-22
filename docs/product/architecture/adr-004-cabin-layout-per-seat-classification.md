# ADR-004 — Cabin layout & per-seat classification

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

Spec prescribes a single aircraft layout: 30 rows × 6 seats (A–F). Cabin has 3 classes (Economy / Business / First). Appendix A surcharges depend on seat *kind* (exit row, front section, aisle, window, middle, bulkhead, etc.). DISCUSS flagged the inference question: "Who decides what counts as an exit row?"

## Decision

Each `Seat` carries its **class and kind** declaratively in the cabin fixture. Pricing looks up surcharges by `(class, kind)`.

```
Seat(id='12C', class=ECONOMY, kind=MIDDLE)
Seat(id='14A', class=ECONOMY, kind=EXIT_ROW)  # exit row marker explicit
Seat(id='3A',  class=BUSINESS, kind=LIE_FLAT_SUITE)
```

**`SeatClass`** enum: `ECONOMY | BUSINESS | FIRST` (Premium Economy deferred per ADR-007).
**`SeatKind`** enum: `STANDARD | MIDDLE | AISLE | WINDOW | EXIT_ROW | FRONT_SECTION | BULKHEAD | LIE_FLAT_SUITE | WINDOW_SUITE | AISLE_ACCESS | PRIVATE_SUITE | FRONT_ROW`

### Default cabin layout (this iteration)

| Rows | Class | Notes |
|---|---|---|
| 1–2 | FIRST | Rows marked FRONT_ROW; row-1 seats A+F are PRIVATE_SUITE |
| 3–6 | BUSINESS | Row 3 LIE_FLAT_SUITE; A/F are WINDOW_SUITE; C/D are AISLE_ACCESS |
| 7–10 | ECONOMY (premium block) | A/F WINDOW; C/D AISLE; B/E MIDDLE; rows 7–10 match Appendix A "Aisle & Window Seats (Rows 6–10)" bucket for +$15 |
| 11–30 | ECONOMY | Standard; row 14 marked EXIT_ROW; B/E always MIDDLE |

(The exact row-to-kind mapping is a fixture, overridable at test time.)

## Alternatives considered

| Alt | Why rejected |
|---|---|
| Infer kind from row number in code (`if row <= 5: FRONT_SECTION`) | Couples pricing to cabin layout; breaks the moment a second aircraft configuration is added. |
| One layout, no kinds | Appendix A requires kind-based surcharges; fails KPI-C1 by design. |
| External YAML file | Good for production, over-engineered for this iteration. `domain/fixtures/cabin.py` is enough. |

## Consequences

- **+** Adding a new aircraft configuration = adding a new cabin fixture; no code change.
- **+** Appendix A surcharges become `SURCHARGES: Dict[Tuple[SeatClass, SeatKind], Money]`, one authoritative table.
- **−** Fixture duplication risk (every test cabin redeclares the layout) — mitigated by a shared `default_cabin()` factory in `tests/fixtures/`.

## Related

ADR-005 (pricing pure function uses this `(class, kind)` lookup), ADR-007 (Premium Economy deferral).
