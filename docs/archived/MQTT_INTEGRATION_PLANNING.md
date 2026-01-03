# MQTT Integration (Planning)

> Archived: implemented; kept for historical context.

## Goal
Add an MQTT integration layer that:
- Lets onboarding/configuration collect MQTT connection details (URL/host, port, username, password, TLS).
- Maintains a long-lived MQTT connection with clear **connection status** surfaced to the frontend.
- Provides a stable API for publishing/subscribing (similar in spirit to the existing `HomeAssistantGateway` wrapper).
- Enables Home Assistant MQTT discovery for a new `alarm_control_panel` entity owned by this app.

This doc focuses on *the app-side MQTT integration boundary and lifecycle*. Home Assistant entity details are covered in `./HA_ALARM_SYNC_PLANNING.md`.

## Non-goals (v1)
- Providing a general-purpose MQTT UI for arbitrary topics.
- Multi-tenant / multi-profile MQTT configuration (assume one app instance, one broker).
- Exactly-once delivery guarantees.

## Architecture overview

### Key design principles
- **Gateway boundary for testability**: application code depends on a Protocol (interface), not a concrete MQTT client.
- **Single connection manager**: keep one managed MQTT connection per app instance; do not open/close per request.
- **Explicit lifecycle**: connect/disconnect/reconnect behavior is owned by a service, not spread across views/tasks.
- **Thin views**: endpoints validate input and delegate to use cases (see `docs/adr/0005-thin-views-and-use-cases.md`).
- **No secrets in logs**: never log passwords or alarm codes (MQTT command payloads).

### Proposed modules (backend)
- `backend/alarm/gateways/mqtt.py`
  - `MqttGateway` Protocol
  - typed exceptions: `MqttNotConfigured`, `MqttNotReachable`, `MqttPublishError`, `MqttSubscribeError`
  - `DefaultMqttGateway` implementation that delegates to a concrete client/manager
- `backend/alarm/mqtt/connection.py`
  - connection manager (connect/reconnect loop, callbacks, subscriptions registry)
- `backend/alarm/mqtt/discovery.py`
  - build/publish Home Assistant discovery payload(s)
- `backend/alarm/mqtt/command_handlers.py`
  - parse/validate command messages and invoke alarm use-cases
- `backend/alarm/use_cases/mqtt_settings.py`
  - update settings, test connection, (re)publish discovery, etc.

## Settings model

### Connection settings (singleton)
Store broker settings in the same way other system configuration is stored today (currently via settings entries / active profile). Even if profiles exist in code, treat it as a singleton config.

`mqtt_connection` (JSON)
```json
{
  "enabled": false,
  "host": "mqtt.local",
  "port": 1883,
  "username": "",
  "password": "",
  "use_tls": false,
  "tls_insecure": false,
  "client_id": "latchpoint-alarm",
  "keepalive_seconds": 30,
  "connect_timeout_seconds": 5
}
```

Notes:
- `password` should be treated as a secret; consider encrypt-at-rest if the project already has a pattern for it.
- `client_id` should be stable but allow override if multiple instances share a broker.

### Alarm entity settings (singleton)
`home_assistant_alarm_entity` (JSON)
```json
{
  "enabled": false,
  "entity_name": "Home Alarm",
  "also_rename_in_home_assistant": true,
  "ha_entity_id": "alarm_control_panel.latchpoint_alarm"
}
```

## Connection status + health reporting

### Runtime status to expose
Expose a read-only runtime status object separate from persisted settings:
```json
{
  "configured": true,
  "connected": true,
  "last_connect_at": "…",
  "last_disconnect_at": null,
  "last_error": null,
  "latency_ms": 42
}
```

Recommended surfaces:
- `GET /api/health/` include `components.mqtt` (frontend already models `mqtt?: ComponentHealth`).
- `GET /api/alarm/mqtt/status/` for richer MQTT-specific details (optional).

### Status calculation
The connection manager should own status and update it on:
- connect success
- disconnect
- auth errors
- publish failures
- subscribe failures

## Backend behavior

### When to connect
Connect when:
- `mqtt_connection.enabled == true`
- app has loaded configuration (DB ready)

Disconnect when:
- `mqtt_connection.enabled` becomes false
- credentials/host change (reconnect with new params)

### Reconnection strategy
Implement exponential backoff with jitter, capped (e.g. 1s → 30s).
Avoid hammering the broker when credentials are wrong: treat auth failures as “degraded” and use a slower retry.

### Subscription registry
Use a small registry so other parts of the app can register subscriptions without owning the client.

Minimum subscriptions for HA alarm entity:
- `latchpoint_alarm/alarm/command` (receive arm/disarm commands with code)

Optional:
- `latchpoint_alarm/alarm/ping` (latency measurement)

## Home Assistant alarm entity via MQTT discovery

### Topics (recommended defaults)
- Discovery config:
  - `homeassistant/alarm_control_panel/latchpoint_alarm/config`
- State:
  - `latchpoint_alarm/alarm/state` (string payload state, or JSON if needed)
- Command:
  - `latchpoint_alarm/alarm/command` (JSON payload including command + code)
- Availability:
  - `latchpoint_alarm/alarm/availability` (`online`/`offline`)
- Error (optional):
  - `latchpoint_alarm/alarm/error` (JSON payload for rejected commands; never includes raw code)

### Discovery payload requirements
Generate and publish a discovery config that:
- sets `name` from `home_assistant_alarm_entity.entity_name`
- uses stable `object_id`/`unique_id` so entity_id stays stable
- defines `state_topic`, `command_topic`, `availability_topic`
- defines `payload_arm_*`/`payload_disarm` values or uses JSON + `command_template`

Rename behavior:
- If `also_rename_in_home_assistant` is true, re-publish discovery config after a name change.
- If false, do not touch discovery config name (app name remains local-only).

## “HA user must enter alarm code” command contract

### Command message shape (proposed)
Publish commands as JSON:
```json
{
  "action": "DISARM",
  "code": "1234"
}
```

Actions:
- `ARM_HOME`
- `ARM_AWAY`
- `ARM_NIGHT`
- `DISARM`

Validation rules:
- `code` is required for `DISARM` (and optionally for arm, depending on system policy)
- Code validation uses the same backend code paths as the app UI (no special bypass)

Failure handling:
- Invalid code: reject, publish no state change, and optionally publish an `error_topic` event for HA automations/logging.

## Use cases + endpoints

### Onboarding flow
Add steps:
1. Enable MQTT integration
2. Collect MQTT broker settings + test connection
3. Collect alarm entity name + (default checked) “Also rename in Home Assistant”
4. Publish discovery config + show “Entity created” guidance

### Settings endpoints (proposed)
- `GET /api/alarm/mqtt/settings/` (returns persisted config; mask password)
- `PATCH /api/alarm/mqtt/settings/` (update config; if enabled, reconnect)
- `POST /api/alarm/mqtt/test/` (attempt connect with supplied/active config)
- `POST /api/alarm/mqtt/publish-discovery/` (force re-publish HA discovery config)
- `PATCH /api/alarm/home-assistant/entity-name/` (or fold into settings) (updates name; optionally re-publish discovery)

## Security notes
- Never return passwords in API responses.
- Don’t log MQTT payloads that include `code`.
- Restrict MQTT config endpoints to admins.
- Consider rate limiting MQTT command processing to avoid brute-force attempts (align with existing code lockout/global rate limiting ADRs).

## Testing plan
- Unit test discovery payload builder (stable ids, topics, name changes).
- Unit test command parsing + validation (requires code for disarm; invalid code doesn’t transition).
- Unit test reconnect behavior on config changes (enable/disable, credential changes).
- API tests for permissions + password masking.

## Rollout checklist
- Add dependency (likely `paho-mqtt`) and ensure it works in Docker.
- Add a worker/service plan for the connection manager (in-process thread vs async loop):
  - v1 recommendation: keep it in the Django process, started on app boot, with careful shutdown handling.
- Add user docs: MQTT broker requirements + HA MQTT integration prerequisites.
