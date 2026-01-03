# ADR 0005: Thin Views and Use-Case Layer (Initial)

## Status
**Implemented**

## Context
Several API endpoints had view-level business logic (e.g., Home Assistant availability checks and entity sync/upsert rules). This makes the views harder to reason about, harder to test, and encourages duplication across endpoints.

## Decision
- Keep DRF views thin: parse/validate request, delegate to an application-level function, map domain/integration errors to HTTP responses.
- Introduce an `alarm.use_cases` module to hold unit-testable “use case” functions.
- Centralize Home Assistant availability checks behind `alarm.gateways.home_assistant.HomeAssistantGateway.ensure_available()` and use explicit exceptions for “not configured” vs “not reachable”.

## Alternatives Considered
- Keep all logic inside DRF views and rely on copy/paste patterns.
- Put all non-view logic into `alarm.services` (continues to grow an already broad module).
- Introduce a full service container / DI framework (more complexity than needed right now).

## Consequences
- Improves SRP: views act as controllers; use cases own application logic.
- Makes logic easier to reuse (e.g., entity sync can be called from a Celery task later).
- Establishes a pattern for future refactors (arm/disarm, rules execution, sensor enrichment).

## Todos
- Apply the same pattern to other “fat” endpoints (alarm transitions, sensor state enrichment).
- Introduce narrow integration interfaces (Protocols) for Home Assistant to improve DIP and allow pure unit tests without patching module globals.
- Consider moving rule evaluation and action execution into distinct use-case modules.
