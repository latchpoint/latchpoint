# ADR 0018: Zigbee2MQTT Integration (Device Sync + Event Ingest)

## Status
**Implemented**

**Note:** The “Alarm panel control via Zigbee events” portion of this ADR is superseded by ADR 0049 (no Zigbee2MQTT code-based arm/disarm pathway).

## Context
We want to support Zigbee sensors (door/window contacts, motion, etc) as first-class alarm inputs, without requiring Home Assistant.

Zigbee2MQTT (Z2M) is a common upstream that exposes:
- **Device inventory** over MQTT (bridge topics; devices/groups/config).
- **Per-device state updates** as JSON payloads on MQTT topics.

Our architecture already assumes:
- MQTT is a reusable **transport** (`transports_mqtt`) and must not be coupled to a single upstream (ADR 0014).
- Upstreams are implemented as **integrations** that adapt external IO into core concepts like the entity registry and sensors (ADR 0014).
- Core → integrations communication is **signals-based** and best-effort (ADR 0015).
- The alarm entity registry is **ours** even when upstream-derived; import/sync is separate from configuration (ADR 0003).

We need a clear plan for how Z2M fits into these boundaries, including settings, APIs, sync, and runtime subscription behavior.

## Decision
Implement Zigbee2MQTT support as a separate Django integration app that reuses the MQTT transport and maps Z2M devices/events into core registry/sensor concepts.

### Integration app
- Add a new Django app: `backend/integrations_zigbee2mqtt/`.
- The integration depends on:
  - `transports_mqtt` for publish/subscribe primitives and connection state.
  - core `alarm` models/use cases for entity registry + sensors.
- Core alarm code must not import Z2M implementation modules (ADR 0014).

### Settings (stored in active profile)
Add integration-specific settings keys (registered in `alarm.settings_registry`) such as:
- `zigbee2mqtt.enabled` (bool)
- `zigbee2mqtt.base_topic` (str, default `zigbee2mqtt`)
- `zigbee2mqtt.discovery_mode` (e.g. `"manual"` vs `"on_enable"`)
- `zigbee2mqtt.allowlist` / `zigbee2mqtt.denylist` (friendly_name and/or IEEE address; default allow-all)
- `zigbee2mqtt.availability` behavior (whether to create/update availability entities)

Z2M itself does not introduce a new secret; it reuses MQTT broker credentials already stored in the MQTT transport settings.

### API surface
Expose integration endpoints under `/api/alarm/integrations/zigbee2mqtt/*` (ADR 0014):
- `GET /status/` (effective enabled state + transport health + last sync info)
- `GET/PATCH /settings/` (integration settings only)
- `GET /devices/` (discovered devices + mapping state)
- `POST /devices/sync/` (pull bridge inventory and upsert registry)

The API should not directly expose raw MQTT messages; it should present stable, integration-owned views of Z2M-derived data.

### Device inventory → entity registry mapping
- Use a sync use case that reads Z2M bridge inventory topics and upserts core entity registry rows with `source="zigbee2mqtt"`.
- Import everything by default (no allowlist filtering), since the goal is to “load all sensors” into the registry first.
- Preserve the “registry is ours” principle:
  - Z2M inventory is a source of truth for what exists upstream, not the final word on how it is configured for the alarm.
  - Alarm sensors reference registry entries; sensors can be created/edited/deleted independently of re-sync (ADR 0003).
- Keep mapping idempotent:
  - Running sync multiple times should converge to the same registry rows.

#### Registry identity and naming
We model Z2M-derived items as `alarm.models.Entity` rows. Each Z2M device can yield multiple entities (one per exposed property), similar to how HA models devices.

- **Stable identity**: prefer IEEE address as the stable identifier (friendly_name can change).
- **Entity ID**: generate a namespaced `entity_id` to avoid collisions with HA-imported entities, e.g.:
  - `z2m_binary_sensor.<ieee>_<prop>`
  - `z2m_sensor.<ieee>_<prop>`
  - `z2m_action.<ieee>` (for action events / keypads where applicable)
- **Domain**: align `domain` to the semantic type (`binary_sensor`, `sensor`, `action`, `device`) for UI filtering and future rules ergonomics, while keeping `entity_id` namespaced.
- **Name**: `${friendly_name} ${prop_label}` (fall back to IEEE if friendly_name missing).
- **Device class**: set when known (e.g. `door`, `motion`, `smoke`, `water`), otherwise leave null.
- **Renames**: never rename `entity_id` due to a `friendly_name` change; update `name` and store upstream identifiers in `attributes`.

### Runtime subscriptions and event ingest
- When enabled, subscribe to Z2M topics needed for:
  - bridge health (e.g. `${base_topic}/bridge/state`)
  - per-device state updates (e.g. `${base_topic}/+/...` patterns as needed)
- Translate per-device payloads into core concepts:
  - update entity “last seen/availability”
  - emit sensor events (via a core use case) for configured sensors
- Wire integration lifecycle via the existing contracts (ADR 0015):
  - on `alarm.signals.settings_profile_changed`, apply integration runtime settings (best-effort; likely via a Celery task).
  - on startup, rely on `python manage.py apply_integration_settings` to establish subscriptions and apply configuration.

### Two-way control (MVP)
Support publishing from the alarm system to Zigbee devices via Zigbee2MQTT, to cover “control outputs” like sirens/lights and basic alarm status indication.

- Add optional integration settings for output mapping, e.g.:
  - a list of target Z2M devices (by IEEE/friendly_name) and the topic to publish to (`${base_topic}/${friendly_name}/set` by default)
  - per-alarm-state payload templates (e.g. map `armed_away` → `{ "state": "ON" }`)
- Trigger publishes on `alarm.signals.alarm_state_change_committed` (ADR 0015) via an async task.
- Keep this best-effort; failures must not affect core transitions.

### Alarm panel control via Zigbee events (MVP)
Support controlling the alarm from Zigbee keypads/buttons via Zigbee2MQTT “action” events.

- Represent action-capable devices as registry entities (e.g. `z2m_action.<ieee>`) so they are visible, taggable, and rule-addressable like other upstream entities.
- Add optional integration settings for control mapping, e.g. a list of:
  - device identifier (IEEE and/or friendly_name)
  - an input matcher (e.g. action string(s) or payload pattern)
  - an alarm action (`arm_home`, `arm_away`, `disarm`, `cancel_arming`)
- On matched events, call the corresponding core use case (authz/rate-limiting rules must remain enforced at the API layer; integration behavior is best-effort and should be conservative by default).

## Alternatives Considered
- Treat Zigbee via Home Assistant only (HA entity discovery/import).
  - Rejected: prevents using Z2M without HA, and reintroduces upstream coupling into core behavior.
- Implement Z2M parsing inside `transports_mqtt`.
  - Rejected: transport must remain upstream-agnostic (ADR 0014).
- Skip persistent mapping; use “live MQTT-only” device list.
  - Rejected: breaks the “registry is ours” model and complicates configuration, rules, and auditability.

## Consequences
- Adds a consistent pattern for MQTT-based upstreams beyond Home Assistant.
- Requires a stable subscription mechanism (shared transport + integration-owned handlers).
- Introduces background processing concerns (timeouts, idempotency, dedupe, message validation).
- Sync and ingest must be careful about:
  - device rename/friendly_name changes
  - missing/partial payloads
  - noisy attributes (avoid turning every numeric change into an “alarm sensor event”)
- “Load all sensors” is implemented as “load all entities into the registry”; sensor configuration remains explicit and separate (ADR 0003).
- Alarm control via Zigbee introduces additional safety considerations (default-off mappings, allow/deny lists, and conservative matching).

## Todos
- Completed MVP implementation (backend integration app, settings, API endpoints, UI tab, tests).
- See ADR 0019 for follow-up hardening work (validation endpoint, ingest mapping improvements, and alarm-control semantics).
