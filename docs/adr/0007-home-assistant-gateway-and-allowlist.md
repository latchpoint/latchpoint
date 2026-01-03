# ADR 0007: Home Assistant Gateway Abstraction

## Status
**Implemented**

## Context
Multiple parts of the backend interact with Home Assistant:
- entity import/sync,
- sensor “live state” enrichment,
- rule actions (`ha_call_service`).

Direct imports of the concrete Home Assistant integration couple business logic to a specific module and make testing harder.

## Decision
- Introduce `alarm.gateways.home_assistant.DefaultHomeAssistantGateway` as an adapter around `integrations_home_assistant`.
- Depend on the `HomeAssistantGateway` Protocol in application code (DIP), using `default_home_assistant_gateway` as the default implementation.

## Alternatives Considered
- Keep using `integrations_home_assistant` directly and patch module-level functions in tests.
- Fully implement an integration layer (repositories, ports/adapters) now (more structure than needed).

## Consequences
- Improves testability and reuse: callers can inject fake gateways.
- Keeps a stable boundary for incremental evolution of the Home Assistant integration.

## Todos
- Consider per-role authorization and rate limiting for HA service calls.
