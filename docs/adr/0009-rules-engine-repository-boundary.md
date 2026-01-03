# ADR 0009: Rules Engine Repository Boundary (DIP)

## Status
**Implemented**

## Context
The rules engine mixed orchestration with ORM access:
- selecting enabled rules,
- reading current entity state,
- selecting due runtimes and ensuring runtime rows.

This made the engine harder to unit test (requires DB) and couples evaluation flow to persistence details.

## Decision
- Introduce `alarm.rules.repositories.RuleEngineRepositories` (a small repository boundary) with a default ORM-backed implementation.
- Keep the public API stable by making repository injection optional in `alarm.rules_engine.run_rules()` and `alarm.rules_engine.simulate_rules()`.

## Alternatives Considered
- Keep ORM calls inline and rely only on integration tests.
- Create a full repository/service layer across the app (heavier structure).
- Use monkeypatching of Django models/QuerySets in tests (brittle).

## Consequences
- Improves DIP: engine depends on abstractions, not concrete ORM queries.
- Enables fast unit tests with in-memory fakes for rules/state/runtime selection.
- Keeps current production behavior unchanged via the default repositories.

## Todos
- Add unit tests that run rules against fake repositories (no DB).
- Consider splitting “scheduler” vs “evaluator” further if rule semantics grow.

