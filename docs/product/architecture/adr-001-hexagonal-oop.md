# ADR-001 — Hexagonal (Ports & Adapters) + OOP paradigm

**Status**: Accepted · **Date**: 2026-04-21 · **Context wave**: DESIGN

## Context

Greenfield Python backend, ~3-hour initial scope, strong DISCUSS-imposed constraints on trust (quote fidelity + audit) and concurrency correctness. Must support growing from 8 carpaccio slices to the full 14-slice backlog without re-layering.

## Decision

Adopt **Hexagonal architecture** (Ports & Adapters) with an **OOP** application layer and a **pure** domain core for pricing and rule engines.

- Four concentric layers: HTTP adapter (driver) → Application Services → Domain → Driven Ports → Driven Adapters.
- The domain has zero I/O; all external effects (persistence, clock, payment, email, audit log) go through ports.
- OOP for services, entities, and adapters. Pricing and rule evaluation are isolated as pure functions in `domain/pricing.py` and `domain/rules.py`.

## Alternatives considered

| Alt | Why rejected |
|---|---|
| Transaction Script (Flask with inline logic) | Loses the trust contract; slices 06/07 (quote TTL + concurrency) get messy. See brief "Option C". |
| Full FP / Functional Core + Imperative Shell | Python is not FP-native; paradigm switching tax outweighs PBT wins that we already get via the pure pricing/rule core. See brief "Option B". |
| Clean Architecture (onion, 5+ layers) | Same structural benefits as hexagonal but with extra ceremony; hexagonal's port/adapter vocabulary maps 1:1 to DISCUSS shared artifacts. |

## Consequences

- **+** Every shared artifact from DISCUSS has a clear home (ports at boundaries, value objects in domain).
- **+** Testing strategy falls out naturally: unit on pure core, integration on adapters, acceptance on HTTP.
- **+** Swap in-memory → SQL later by writing one adapter module; no domain change.
- **−** Slightly more files than a transaction-script approach; junior devs must internalize "no business logic in adapters".
- **−** Pure functions in a Python OOP codebase require convention discipline (no hidden global state, no clock access in `pricing.py`).

## Related

ADR-005 (pricing/rule engines as pure functions), ADR-008 (in-memory persistence + lock primitive).
