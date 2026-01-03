# ADR 0014: Alarm Core + Integrations Decomposition (MQTT, Home Assistant, Z-Wave JS)

## Status
**Implemented**

## Context
`backend/alarm/` currently contains both:
- **Core alarm domain** (state machine, snapshots/events, rules engine, sensors/entity registry, websocket updates), and
- **External integrations** (Home Assistant API, MQTT broker transport, HA-over-MQTT discovery/alarm entity behavior, Z-Wave JS connectivity).

As integrations expand (MQTT reuse beyond HA, Z-Wave JS features, future upstreams like Zigbee2MQTT), this coupling creates recurring problems:
- **Unclear dependency directions**: core code ends up importing integration-specific modules (or integration modules import each other), increasing refactor risk.
- **Harder tests by default**: importing core logic can pull in integration code with side effects or network expectations.
- **API/URL and settings confusion**: transport concerns, integration concerns, and core concerns mix in the same namespace.

We already have relevant precedents:
- Thin views delegate to use cases (ADR 0005).
- The alarm state machine is decomposed into focused modules, with `alarm.services` as a compatibility facade (ADR 0008).
- External IO should be behind gateways (ADR 0007), and tests should not hit HA by default (ADR 0010).
- MQTT should be transport-only, with HA-over-MQTT behavior living in an integration module (ADR 0013).
- Z-Wave JS needs a gateway + connection manager split (ADR 0012).

We want a structure that makes it easy to add/remove integrations without destabilizing the alarm domain.

## Decision
We formally decompose `backend/alarm/` into:

1) **Alarm Core (domain + application orchestration)**
- Existing “core” packages remain the canonical home:
  - `alarm/state_machine/*` (domain transitions/timing/events/snapshot persistence)
  - `alarm/use_cases/*` (application orchestration invoked by API views)
  - `alarm/rules_engine.py` and `alarm/rules/*` (stable public API + internals)
  - sensors/entity registry models and CRUD, including import/sync as a core concept (the “registry” is ours even when upstream-derived)
- Views/serializers remain thin and may live with core features (per current conventions), but must not import integration implementations directly.

2) **Transports (shared connectivity primitives)**
- Shared IO transports are reusable building blocks for integrations:
  - Example: MQTT transport (ADR 0013).
  - Transports provide connection/config/status/publish-subscribe primitives and are not HA/ZWave specific.

3) **Integrations (adapters that bind upstreams to core concepts)**
- Integrations own upstream-specific behavior:
  - Home Assistant: API calls, entity/service discovery, HA-shaped payloads.
  - HA-over-MQTT alarm entity: discovery payloads, HA topics/constants, command handling.
  - Z-Wave JS: WebSocket connection manager/gateway and node/value mapping into the entity registry.
- Integrations may:
  - define their own settings keys (registered in the settings registry),
  - expose their own API endpoints (status/settings/test/sync),
  - run their own background tasks,
  - translate upstream events into core events (entity registry updates, sensor events, rule triggers).

### Django app layout (separate `INSTALLED_APPS`)
We implement the decomposition as separate Django apps (without moving core models initially):
- `alarm` (core domain + API + websocket + models)
- `transports_mqtt` (MQTT transport: config/status/test + connection manager)
- `integrations_home_assistant` (Home Assistant integration: API/status/entities/notify + HA-over-MQTT alarm entity + HA notifications task)
- `integrations_zwavejs` (Z-Wave JS integration: config/status/test + connection manager + entity sync + commands)

Compatibility shims are explicitly **not** part of the steady state: code moves are accompanied by import rewrites so that the real app modules are used directly.

### Dependency rules (enforced by convention and tests)
- **Core MUST NOT import integration implementations**.
  - Core may import gateway `Protocol`s and emit signals at stable hook points.
- **Integrations MAY import core** (use cases, repositories, models) but should prefer stable core entrypoints where available.
- **Integrations MUST NOT import each other**; shared functionality belongs in core or a transport.
- **Transports MUST NOT import integrations**; integrations depend on transports, not the reverse.

### Integration dispatch boundary (core → integrations): Django signals
Core emits integration-relevant events through a small, stable set of Django signals fired from “on-commit” boundaries:
- `alarm.signals.alarm_state_change_committed` (after an alarm state transition commit)
- `alarm.signals.settings_profile_changed` (after settings profile updates/activation commit)

Integrations connect handlers in their own `AppConfig.ready()` methods and perform best-effort side effects (publish MQTT state/discovery, apply runtime connection settings, etc). Core does not import integration modules.

### Integration lifecycle: explicit apply command
We avoid background startup threads for applying settings. Instead, we provide an explicit boot-time command:
- `python manage.py apply_integration_settings`

This command applies the active profile’s integration settings to runtime gateways and (best-effort) publishes HA MQTT alarm entity discovery when enabled. It is intended to be run by the deployment/startup process after migrations.

### HTTP API and WebSocket surfaces
- Preserve existing externally-visible endpoints while moving ownership to the new apps.
- For new integration endpoints, prefer a stable namespace:
  - `/api/alarm/integrations/<integration>/*` for integration-specific settings/status/sync actions.
  - Transport-only endpoints remain transport-scoped (e.g., `/api/alarm/mqtt/*` for broker connectivity).
- WebSocket remains core-owned (`/ws/alarm/`) and publishes core domain updates; integrations can enrich core state via the registry/sensors, rather than emitting separate WS protocols.

Implementation note:
- URL routing for integration apps is defined at the project level (`config.urls`) via `include(...)` so that app ownership can change without changing the externally visible paths.

## Alternatives Considered
- Keep everything in `backend/alarm/` without a formal boundary.
  - Pros: no restructuring work.
  - Cons: continued coupling, harder testing, harder reuse of transports, repeated refactor costs.

- Split into multiple Django apps with a direct-call dispatch layer (core imports a dispatcher).
  - Pros: explicit, easy to follow.
  - Cons: dispatcher tends to become a central dependency and can reintroduce coupling over time.

- Split only by “Home Assistant vs non-Home Assistant”.
  - Pros: aligns with today’s biggest integration.
  - Cons: does not scale to multiple upstreams and does not clarify transport-vs-integration responsibilities (ADR 0013).

- Separate Django apps + signals boundary (chosen).
  - Pros: normal Django pattern for decoupling; avoids core importing integration modules; easy to extend.
  - Cons: best-effort delivery; requires discipline to keep signals small and stable (see ADR 0015).

## Consequences
- Clearer architecture: core remains stable while integrations evolve independently.
- Better testability: core unit tests avoid importing HA/MQTT/Z-Wave JS implementations; integrations can be tested with mocked gateways/managers and feature flags.
- Easier extensibility: new upstreams (e.g., Zigbee2MQTT) fit into a known pattern (transport + integration + mapping into core entity registry).
- Some upfront refactor cost: code moves, import updates, and URL/view re-wiring while preserving behavior.
- Operationally safer evolution: Celery tasks can keep stable task names via explicit task naming even when implementation lives in a different app module.
- Signals are best-effort and in-process; critical side effects should use tasks/outbox patterns if reliability requirements increase (ADR 0015).

## Todos
- Keep adding import-boundary guardrails so core stays independent of concrete IO implementations.
- Consider splitting `integrations_home_assistant` further if additional HA-only integrations accumulate (e.g., `integrations_home_assistant_mqtt`).
- Decide whether any models/status tables should migrate out of `alarm` into integration apps (only if/when it provides real value; this is optional and higher-migration-cost).
- Document and keep stable the signal contracts (`alarm_state_change_committed`, `settings_profile_changed`) so integrations can rely on them safely.
- See ADR 0015 for the signal contract.
- Ensure deployment runs `python manage.py apply_integration_settings` after migrations so integrations apply settings on boot without hidden startup side effects.
