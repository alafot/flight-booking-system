# ADR-003 — Money as `Decimal` with banker's rounding

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

Spec (Appendix B) gives three worked examples that must match to the cent (228.74 / 897.00 / 1944.00 USD). `float` cannot satisfy this; we need a deterministic rounding rule. KPI-C1 asserts all three.

## Decision

- All money values use `decimal.Decimal`.
- Exactly one `Money` value object in `domain/model/money.py`, quantized to **2 decimal places** with `ROUND_HALF_EVEN` (banker's rounding).
- `Money` is immutable; arithmetic returns a new `Money`.
- **`float` is forbidden** in the domain layer. A lint rule (ruff + custom check or mypy plugin) will enforce this.

## Verification against spec

Applying the pricing formula `base × demand × time × day` with `ROUND_HALF_EVEN` at the end:

| Example | Inputs | Expected | Computed |
|---|---|---|---|
| 1 | 299 × 1.00 × 0.90 × 0.85 | 228.74 | `Decimal('228.735')` → `228.74` |
| 2 | 299 × 1.60 × 1.50 × 1.25 | 897.00 | `Decimal('897.000')` → `897.00` |
| 3 | 299 × 2.50 × 2.00 × 1.30 | 1944.00 | `Decimal('1943.500')` → `1944.00` (banker's rounds 0.5 to nearest even: 1944 is even) |

## Alternatives considered

| Alt | Why rejected |
|---|---|
| `float` | Non-deterministic cent-level results; fails KPI-C1 on principle. |
| `ROUND_HALF_UP` | Would also satisfy the three examples, but half-even is the accounting standard; less bias. |
| Integer cents (`int`) | Works, but `Money * Decimal('0.90')` becomes awkward with mid-computation scaling; `Decimal` is cleaner. |

## Consequences

- **+** Deterministic pricing under any input; essential for KPI-T1 quote fidelity and KPI-T3 audit replay.
- **+** `hypothesis` can generate `Money` values safely.
- **−** All boundary tests must use `Decimal` literals; any `0.1 + 0.2` in the code is a bug waiting to happen — caught by the float-in-domain lint.

## Related

ADR-005 (pricing as pure function), KPI-C1 (spec example verification), KPI-T1 (quote fidelity).
