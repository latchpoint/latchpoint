# Zigbee2MQTT Integration

This project supports Zigbee2MQTT (Z2M) without requiring Home Assistant.

Z2M is integrated via the shared MQTT transport and maps Z2M devices/events into the alarm entity registry.

## Prereqs
- MQTT broker reachable and configured in **Settings → MQTT**
- Zigbee2MQTT connected to the same broker

## Configure
In **Settings → Zigbee2MQTT**:
- Enable Zigbee2MQTT
- Set `base_topic` (default: `zigbee2mqtt`)

## Sync devices (recommended)
Use **Sync devices** to import Z2M devices into the entity registry.

This:
- requests devices from `${base_topic}/bridge/request/devices`
- reads `${base_topic}/bridge/response/devices`
- upserts `alarm.models.Entity` rows with `source="zigbee2mqtt"`

## Runtime ingest
When enabled, the backend subscribes to `${base_topic}/+` and ingests:
- state updates (best-effort, per exposed property)
- `action` events as a `z2m_action.*` entity state (when supported by the device)

The integration keeps a cached mapping of `friendly_name -> ieee_address` and refreshes it on MQTT connect and when enabling Zigbee2MQTT.

## Control Zigbee devices via rules
Use **Rules** to publish Zigbee2MQTT “set” payloads using the synced entities:
- WHEN: match on entity state (e.g., occupancy, contact, action strings)
- THEN: use “Zigbee2MQTT set value” to publish `{ "<property>": <value> }` to `${base_topic}/${friendly_name}/set`

## Notes / gotchas
- Zigbee2MQTT set-value actions require entity expose metadata (sync devices first).
