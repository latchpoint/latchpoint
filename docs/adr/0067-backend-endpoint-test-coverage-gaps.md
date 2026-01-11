# ADR 0067: Backend Endpoint Test Coverage Gaps

## Status
Proposed

## Context
The backend test suite includes a mix of unit tests and integration-style tests (DRF API tests + Channels WebSocket tests), but not every HTTP endpoint has direct coverage.

When endpoints are untested, regressions tend to show up as:
- broken auth/permissions on new/changed routes
- response-shape drift (especially with the ADR 0025 response envelope)
- missing error handling for common failure modes (invalid input, not configured, external service down)

This ADR inventories the current “missing endpoint coverage” and recommends the next tests to add.

## Decision
Add a minimal “endpoint coverage baseline” for each backend endpoint that is not already exercised in tests:
- **Auth/permission smoke test**: unauthenticated returns 401; role-restricted endpoints return 403 for non-admins.
- **Happy-path smoke test**: returns 200/201/204 with response envelope (`{"data": ...}`) and essential keys.
- **Error-path smoke test**: covers at least one representative error per endpoint (validation error / not found / integration unavailable).

External integrations must be tested without network I/O by patching the relevant gateways/handlers.

## Alternatives Considered
- Do nothing and rely on unit tests: faster suite, but breaks are discovered later and require more debugging.
- Add broad “end-to-end” tests only: higher confidence, but slower, more fragile, and harder to keep deterministic.
- Enforce 100% endpoint coverage: ideal in theory, but too expensive for development-stage churn.

## Consequences
- More tests, slightly longer runtime.
- Better confidence when refactoring views/serializers and when changing auth/permissions.
- Clear “what’s missing” checklist for incremental improvements.

## Recommended Tests To Add
This list is organized by URL name (as defined in `backend/**/urls.py`).

### Alarm dispatcher (ADR 0057)
- `dispatcher-status` (GET)
  - Requires auth (401 without auth).
  - Returns 200 and a stable set of top-level keys; patch `alarm.dispatcher.get_dispatcher_status` to a known payload.
- `dispatcher-config` (GET)
  - Requires auth.
  - Returns config keys with numeric types; patch `alarm.dispatcher.config.get_dispatcher_config`.
- `dispatcher-suspended-rules` (GET/DELETE)
  - Requires auth.
  - GET returns suspended rules with expected fields (create `RuleRuntimeState(error_suspended=True)` + related `Rule`).
  - DELETE with `?rule_id=` clears a single suspension; DELETE without clears all.
  - DELETE invalid `rule_id` returns 404 (note: current payload is not ADR 0025-shaped; lock behavior in tests or update endpoint to raise `NotFoundError`).

### Rules metadata
- `alarm-rules-supported-actions` (GET)
  - Requires auth.
  - Non-admin does not receive `admin_only` actions.
  - Admin receives `admin_only` actions (current implementation checks `user.is_staff`; tests should set `is_staff=True` explicitly).

### MQTT transport
- `mqtt-status` (GET)
  - Requires auth.
  - Returns 200 and includes connection status keys.
  - Patch `transports_mqtt.views.mqtt_gateway` to avoid real connections and to assert `apply_settings(...)` is invoked best-effort.

### Zigbee2MQTT integration
- `zigbee2mqtt-status` (GET)
  - Requires auth.
  - Patch `integrations_zigbee2mqtt.views.mqtt_connection_manager.get_status` and `integrations_zigbee2mqtt.status_store` functions to assert `connected` logic.
- `zigbee2mqtt-devices` (GET)
  - Requires auth.
  - Returns only `Entity(source="zigbee2mqtt")`, ordered by `entity_id`.
- `zigbee2mqtt-devices-sync` (POST)
  - Requires admin role (403 for non-admin).
  - Happy path returns the sync result; patch `integrations_zigbee2mqtt.runtime.sync_devices_via_mqtt`.
  - Error paths map to standardized errors:
    - invalid config -> 400 (`ValidationError`)
    - timeout -> 408/504 equivalent (whatever `OperationTimeoutError` maps to)
    - unexpected -> 503 (`ServiceUnavailableError`)

### Notifications API
No notification API endpoints appear to have direct HTTP tests today (handlers/outbox are covered).

- `provider-list` (GET/POST)
  - Requires auth.
  - With no active profile: returns an empty list.
  - Create requires active profile (currently raises `ValidationError("No active profile.")`).
  - Duplicate provider names return a DRF validation error for `name`.
- `provider-detail` (GET/PATCH/DELETE)
  - Requires auth.
  - Not found returns 404 (`NotFoundError`).
  - Update supports partial updates; delete returns 204.
- `provider-test` (POST)
  - Requires auth.
  - Patch `notifications.views.get_dispatcher().test_provider` to return deterministic result.
- `provider-types` (GET)
  - Requires auth; returns list of handler metadata and schema fragments.
- `log-list` (GET)
  - Requires auth.
  - With no profile/providers: empty list.
  - With logs present: returns most-recent-first and capped at 100.
- `pushbullet-devices` (GET)
  - Requires auth.
  - Missing token -> 400 (`ValidationError`).
  - With `access_token` query param -> patch `PushbulletHandler.list_devices`.
  - With `provider_id` query param -> patch `decrypt_config(...)` to return token; verify provider not found and encryption-not-configured cases.
- `pushbullet-validate-token` (POST)
  - Requires auth.
  - Valid token -> returns `{valid: true, user: {...}}`; invalid token -> `{valid: false, error: ...}` (patch `PushbulletHandler.get_user_info`).
- `ha-services` (GET)
  - Requires auth; patch `HomeAssistantHandler.list_available_services`.
- `ha-system-provider-test` (POST)
  - Requires auth; patch `integrations_home_assistant.api.get_status` and `list_notify_services`.
  - Not configured / not reachable -> returns `ServiceUnavailableError` response.

## Todos
- Add `backend/alarm/tests/test_dispatcher_api.py` (dispatcher endpoints).
- Extend `backend/alarm/tests/test_api.py` or add `backend/alarm/tests/test_supported_actions_api.py` (supported actions).
- Add `backend/transports_mqtt/tests/test_mqtt_status_api.py` (MQTT status).
- Extend `backend/alarm/tests/test_zigbee2mqtt_api.py` (status/devices/sync).
- Add `backend/notifications/tests/test_api.py` (providers/types/logs/pushbullet/HA helper endpoints).
- Add a small “coverage inventory” dev script (optional) that lists named URL patterns not referenced by `reverse(...)` in tests, to keep this ADR checklist current.

