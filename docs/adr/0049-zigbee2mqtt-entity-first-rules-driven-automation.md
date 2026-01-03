# ADR 0049: Zigbee2MQTT Entity-First, Rules-Driven Automation

## Status
Implemented

## Context
Users want Zigbee2MQTT (Z2M) to feel like other integrations (e.g. Z-Wave JS): devices show up as entities with clear capabilities, and automations are created through the rules UI.

The prior approach added a bespoke “mappings” schema/UI (input mappings for alarm control; output mappings for publishing JSON payloads). While flexible, it is not the easiest UX:
- Requires users to understand Z2M topics/payload shapes and state keys.
- Duplicates capabilities that already exist in the rules engine.
- “Alarm control via Zigbee keypad/panel code” is hard to validate without hardware, and adds a security-sensitive code path.

## Decision
1) **Remove Zigbee alarm control via panel code + input mappings**
   - Do not support arming/disarming via Zigbee2MQTT `action` + `code` payloads.
   - Keep `action` events as entity state (`z2m_action.*`) so they can be used in rules if needed.

2) **Make Zigbee2MQTT entity-first**
   - Z2M device sync continues to upsert entities with `attributes.zigbee2mqtt.definition/expose` metadata.
   - Users create automations by referencing these entities in the rules builder (e.g. motion `occupancy`, light `state/brightness`).

3) **Drive Zigbee control through rule actions, not mapping JSON**
   - Implement Z2M control as a gateway that can publish to the correct `${base_topic}/${friendly_name}/set` topic.
   - Build payloads from the entity’s stored Z2M expose metadata (capability-driven control), so users pick an entity + a control (on/off, brightness, etc.) instead of writing JSON.

4) **Remove `output_mappings`**
   - Publish Zigbee device control via rules actions instead of alarm-state-driven mapping JSON.
   - Eliminate the `output_mappings` feature/UI to reduce surface area and keep automation in one place (rules).

## Alternatives Considered
- Keep bespoke mappings UI (ADR 0048).
  - Rejected: not the easiest UX; duplicates the rules engine and requires users to reason about JSON payloads.
- Delegate automation to Home Assistant / Node-RED.
  - Rejected (for now): increases dependency surface and breaks the goal of being HA-optional.

## Consequences
- Simplifies Zigbee2MQTT settings and removes a security-sensitive, hard-to-test alarm-control pathway.
- Requires implementing Z2M entity control actions (and the capability parsing needed to build correct payloads).
- Rules UI becomes the single place users learn to automate, which reduces cognitive load.

## Implementation Status (Today)
- Entity-first device sync exists and stores `attributes.zigbee2mqtt.definition` + per-entity `attributes.zigbee2mqtt.expose`.
- Z2M ingest updates entity state (including `z2m_action.*`) and can optionally trigger rules runs.
- Panel-code alarm control and input mappings are not supported.
- Legacy `output_mappings` has been removed; Zigbee control is rules-driven.
- Zigbee2MQTT control is available as guided rule actions (switch on/off, light on/off + brightness) plus an advanced set-value action.

## Todos
- Backend
  - Add more guided actions as needed (e.g., color temperature, scenes), driven by expose metadata.
- Frontend
  - Improve entity picking UX for Z2M devices (show friendly device name + property).
- Migration / cleanup
  - Remove remaining UI/setting fields related to panel code and input mappings (done as part of this pivot).
  - Ensure remaining docs/plans reference the rules-driven control path (no `output_mappings`).
