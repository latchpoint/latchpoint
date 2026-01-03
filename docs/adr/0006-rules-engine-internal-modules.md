# ADR 0006: Rules Engine Internal Decomposition (SOLID)

## Status
**Implemented**

## Context
`alarm.rules_engine` combined multiple responsibilities:
- Rule condition parsing + evaluation (AST operators like `all/any/not/entity_state/for`).
- Runtime state management for `FOR` scheduling and cooldown checks.
- Action execution (alarm transitions and Home Assistant service calls).
- Audit logging (`RuleActionLog`).

This made the module harder to test in isolation and encouraged changes that touched unrelated code paths.

## Decision
- Keep the public API stable (`run_rules()`, `simulate_rules()` in `alarm.rules_engine`).
- Split internals into focused modules under `alarm.rules`:
  - `conditions.py`: AST evaluation + explain traces.
  - `runtime_state.py`: cooldown + runtime row helpers.
  - `action_executor.py`: executes “then” actions with explicit dependencies (Protocols) for alarm services and HA gateway.
  - `audit_log.py`: persists rule execution audit logs.

## Alternatives Considered
- Keep a single `rules_engine.py` and use regions/comments to separate concerns.
- Move everything into `alarm.services` (would further centralize unrelated responsibilities).
- Introduce a full DI container (more complexity than needed for current scale).

## Consequences
- Improves SRP and reduces churn: changes to evaluation, scheduling, actions, or logging are isolated.
- Enables DIP for rule actions: `action_executor.execute_actions()` can be unit tested with fakes instead of patching module globals.
- Keeps external imports stable for existing endpoints/tests.

## Todos
- Add “stop-after-fire” and conflict resolution policy as explicit engine configuration.
- Add validation for HA service calls (security posture).
- Add more unit-level tests around condition evaluation and action execution using fake gateways.
