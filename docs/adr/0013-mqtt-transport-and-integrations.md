# ADR 0013: MQTT Transport Separate From HA/Zigbee2MQTT Integrations

## Status
Superseded by ADR 0014

## Context
Today, our MQTT feature is partially a transport layer (broker connection, publish/subscribe) and partially a Home Assistant (HA) integration (MQTT discovery payloads, HA alarm entity conventions, HA-specific topics, and HA-facing “alarm entity” settings and status tracking).

This coupling has two costs:
- It makes it hard to reuse MQTT for other integrations (e.g. Zigbee2MQTT) without inheriting HA-specific assumptions.
- It introduces an architectural dependency from core alarm code (state machine) into an HA-shaped MQTT module (e.g. state changes scheduling HA-MQTT publishes), which makes boundaries unclear and complicates testing and future evolution.

We want MQTT to be a reusable transport for multiple integrations, including:
- Home Assistant (alarm control panel via MQTT discovery + commands)
- Zigbee2MQTT (future; device and event flows that are not HA discovery-shaped)

## Decision
We separate MQTT into a transport layer and move HA-over-MQTT alarm entity behavior into an integration module.

- `alarm.mqtt.*` becomes “transport only”:
  - Connection settings, connection manager, publish/subscribe primitives, generic connectivity status.
  - No HA discovery topics, no HA payload formats, no HA-specific settings, no HA-specific persisted status.

- HA MQTT alarm entity becomes an integration module:
  - New module location: `alarm/integrations/home_assistant/mqtt_alarm_entity/*` (exact structure may evolve).
  - Owns HA discovery payload building, HA topics/constants, and the MQTT command handler for alarm actions.
  - Depends on a narrow MQTT interface (gateway/protocol) rather than “the mqtt feature”.

- Core alarm code (state changes) publishes integration events through a dispatch boundary:
  - A small integration dispatch module is called from state-machine/on-commit hooks (e.g. “alarm state changed”).
  - The state machine does not import HA or integration-specific modules directly.

- API surface is split by responsibility:
  - MQTT transport endpoints remain under `/api/alarm/mqtt/*` and cover broker connectivity only.
  - Integration endpoints live under a generalized `/api/alarm/integrations/*` namespace from day one (including HA and Zigbee2MQTT).
  - This is a single refactor; we do not preserve deprecated compatibility endpoints.

## Alternatives Considered
- Keep current structure (HA MQTT alarm entity code inside `alarm.mqtt`).
  - Pros: fewer code moves in the short term.
  - Cons: blocks MQTT reuse for Zigbee2MQTT and keeps core alarm code coupled to HA-shaped MQTT modules.

- Split by “Home Assistant vs MQTT” only (keep an `integrations_home_assistant.mqtt_*` layer without a generic integrations boundary).
  - Pros: improves naming and reduces confusion.
  - Cons: still leaves no scalable pattern for multiple non-HA MQTT integrations and does not address state-machine coupling cleanly.

## Consequences
- Clearer boundaries: MQTT becomes a shared transport; HA/Zigbee2MQTT become integrations that consume it.
- Better testability: core alarm logic can be tested without importing HA/MQTT integration modules; integrations can be tested with mocked MQTT gateways.
- Some migration work:
  - Code moves and import updates.
  - URL + frontend updates (no compatibility layer).
  - Model/status renames to avoid conflating transport status with HA publishing status.

## Todos
- Implement integration dispatch boundary (state machine -> integrations) and remove direct imports from core alarm code into HA MQTT modules.
- Move HA MQTT alarm entity code out of `alarm.mqtt` into an HA integration module; keep MQTT transport primitives in `alarm.mqtt`.
- Split DRF views/urls:
  - Keep `/api/alarm/mqtt/settings|status|test` as transport-only.
  - Add integration endpoints under `/api/alarm/integrations/*` for HA alarm entity settings and discovery publishing.
- Rename `MqttIntegrationStatus` to a HA integration-specific model (e.g. `HomeAssistantMqttAlarmEntityStatus`).
- Add a Zigbee2MQTT integration stub (module boundary + settings shape) to validate reuse early.
- Update docs to reflect “MQTT transport + integrations” mental model.

## Notes
This ADR was written during early exploration of splitting MQTT transport from integrations. The final design is captured in `docs/adr/0014-alarm-core-and-integrations-decomposition.md`.
