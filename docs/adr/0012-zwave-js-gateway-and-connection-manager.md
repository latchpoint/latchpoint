# ADR 0012: Z-Wave JS Gateway + Connection Manager

## Status
Proposed

## Context
We want first-class Z-Wave support without requiring users to route everything through Home Assistant entities.

Z-Wave networks are typically managed by an external service (target: `zwave-js-server`) which exposes a WebSocket API for:
- long-lived connection state,
- event streams (node/value updates),
- commands (set values, lock/unlock, etc).

This repo already has two relevant integration patterns:
- **Gateway abstraction for external IO** (`alarm.gateways.home_assistant`) to keep business logic DI-friendly.
- **Connection manager for long-lived connections** (`transports_mqtt.manager.MqttConnectionManager`) to centralize reconnect + status + best-effort behavior.

We need a similar approach for Z-Wave JS so that:
- API views remain thin and don’t embed connection logic,
- rule actions and sensor enrichment can depend on a stable interface,
- tests can run without hitting real Z-Wave infrastructure by default.

## Decision
Introduce a Z-Wave JS integration split into:

1) **A management object that owns the connection**
- Add `backend/integrations_zwavejs/manager.py` with a `ZwavejsConnectionManager` responsible for:
  - applying persisted settings and maintaining a best-effort long-lived WebSocket connection (when enabled),
  - reconnect/backoff and explicit `disconnect()` on disable,
  - maintaining an in-memory “last known” cache of node/value state (bounded + optional),
  - dispatching inbound events to subscribers (callbacks/hooks),
  - exposing a pure status object (`configured/enabled/connected/last_error/last_connect_at/...`),
  - providing a separate `test_connection(settings)` for onboarding validation.

2) **A gateway Protocol boundary**
- Add `backend/alarm/gateways/zwavejs.py` analogous to `alarm.gateways.home_assistant` / `alarm.gateways.mqtt`:
  - `ZwavejsGateway` Protocol defining only the operations application code needs (status, apply_settings, test_connection, and narrowly-scoped command/query methods),
  - `DefaultZwavejsGateway` that delegates to the singleton manager (e.g., `zwavejs_connection_manager`).

3) **Settings + API surface**
- Add alarm-profile settings entries similar to MQTT:
  - `zwavejs_connection`: `enabled`, `ws_url` (supports `ws://` and `wss://`), optional auth (e.g. `api_token`), timeouts, and reconnect/backoff tuning.
  - Use `backend/alarm/crypto.py` to encrypt stored secrets (token) at rest, and a helper in `backend/integrations_zwavejs` to normalize/mask/decrypt for runtime.
- Add DRF endpoints similar to MQTT:
  - `GET /api/alarm/zwavejs/status/`
  - `GET/PATCH /api/alarm/zwavejs/settings/`
  - `POST /api/alarm/zwavejs/test/`
  - Optional (later): `GET /api/alarm/zwavejs/nodes/` and `POST /api/alarm/zwavejs/entities/sync/`

4) **Entity model integration**
- Treat Z-Wave JS as another “upstream entity source” alongside HA:
  - Provide a sync/import step that converts Z-Wave node/value metadata into our existing entity registry records.
  - Use a stable, namespaced key scheme for imported entities based on Z-Wave JS ValueID components (not transient internal numeric IDs), e.g.:
    - `zwavejs:<home_id>:<node_id>:<endpoint>:<command_class>:<property>:<property_key_or_->`
  - Add/extend the “source” concept for entity registry UI filtering so users can view Z-Wave entities separately from HA-derived entities.

5) **Rules/actions safety**
- Support commands from day 1 (initially: lock/unlock and value set operations), routed through the `ZwavejsGateway` and protected by validation (types/ranges) before sending commands.

## Alternatives Considered
- Rely on Home Assistant only (import Z-Wave devices via HA and control them via HA service calls).
  - Simpler, but couples Z-Wave support to HA availability and HA entity naming/stability.
- Directly embed a Z-Wave JS client in views/use cases without a manager/gateway split.
  - Faster to start, but repeats connection logic, complicates tests, and makes future safety controls harder.
- Run Z-Wave JS inside this app’s containers.
  - Operationally complex (USB/device passthrough, supervisor responsibilities) and out-of-scope for this project right now.

## Consequences
- Clear separation of concerns: connection lifecycle in one place, business logic depends on a small interface.
- Enables incremental rollout:
  - start with status/settings/test endpoints,
  - later add entity import + rule actions.
- Adds a new external integration surface (WebSocket client + dependency selection), which must be carefully controlled and test-gated.
- No assumption about where Z-Wave JS runs (bare metal, another container, remote host): we always connect via configured WebSocket URL.

## Todos
- Decide the concrete client approach:
  - implement the minimal WebSocket protocol ourselves, or
  - adopt a dedicated python client library and wrap it behind the manager.
- Add settings registry entries + serializers for `zwavejs_connection`.
- Add a persisted status store (DB or existing settings/status pattern) if we need durability across restarts.
- Add “integration disabled in tests by default” behavior, mirroring ADR 0010 (e.g., `ALLOW_ZWAVEJS_IN_TESTS=true`).
- Define the initial entity mapping (which Z-Wave values become candidate sensors/locks) and finalize/document the ID scheme.
- Define and enforce the initial command validation policy (and error shape).
