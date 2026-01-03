# Home Assistant Alarm Entity (Planning)

> Archived: implemented; kept for historical context.

## Summary
Instead of syncing an existing Home Assistant alarm entity (e.g. Alarmo/manual alarm) into this app, the onboarding flow should create/connect a **new Home Assistant `alarm_control_panel` entity** that represents *this app’s* alarm state machine.

Users must be able to **rename the Home Assistant alarm entity from this app’s Settings**, and have that rename reflected in Home Assistant.

Important constraint: Home Assistant entities are created by HA integrations. If we explicitly do **not** ship a Home Assistant custom integration, the practical way to “create an `alarm_control_panel` entity” from this app is **MQTT discovery** (requires HA’s MQTT integration + a broker). This plan assumes MQTT discovery; see `./MQTT_INTEGRATION_PLANNING.md`.

## Goals
- Create/connect a dedicated HA `alarm_control_panel` entity for this app (**one per app instance**).
- HA entity mirrors this app’s authoritative alarm state (near real-time).
- HA can arm/disarm the app via supported commands.
- Onboarding covers everything needed to get HA + app talking.
- Admins can rename the HA alarm entity from this app at any time.

## Non-goals (v1)
- Importing or mapping an existing HA alarm entity into this app.
- Multiple alarms per single app instance (multi-panel / multi-home).
- Making HA the source of truth for state.
- Shipping/maintaining a Home Assistant custom integration.
- Preserving HA-side name overrides (v1: app can overwrite HA name when requested).

## Why change from “sync existing entity”?
Syncing an existing HA alarm entity makes it unclear which system is authoritative and increases edge cases (state mapping, arming delays, competing automations). Creating a dedicated HA entity keeps responsibilities crisp:
- App owns state machine + rules.
- HA owns dashboards + automations + voice assistants.
- Integration boundary is commands/events, not shared state.

## Current repo context
- HA connectivity helpers exist via `backend/alarm/home_assistant.py` + `backend/alarm/gateways/home_assistant.py` (preferred boundary).
- Token auth exists for compatibility and non-browser clients; WS `?token=` fallback exists.
- Frontend already has onboarding and settings patterns (`docs/ONBOARDING_PROCESS_PLANNING.md`).

## Proposed approach (no HA custom integration): MQTT discovery
Use HA’s built-in MQTT integration and discovery protocol so this app can “create” an `alarm_control_panel` entity in HA by publishing a discovery config payload to the MQTT broker.

High-level flow:
1. User configures MQTT broker in HA (or already has it).
2. User enables MQTT settings in this app (broker URL + credentials).
3. This app publishes HA MQTT discovery config for `alarm_control_panel.latchpoint_alarm` (or similar stable object id).
4. This app publishes state updates to a `state_topic`.
5. HA publishes arm/disarm commands (including the user-entered code) to a `command_topic`.
6. This app validates the code and executes the transition through its existing API/use cases/state machine.

Prerequisites:
- HA MQTT integration enabled and connected to a broker.
- This app can connect to the same broker.

## User-facing behavior

### Onboarding (app)
Add a “Home Assistant” step focused on MQTT, before setup completes:
1. **Alarm entity name**: ask for a display name (default: `${home_name} Alarm`).
2. **MQTT broker**: collect broker connection details (host/port/user/pass/TLS).
3. Show HA instructions: ensure MQTT integration is set up (one-time), and verify “MQTT discovery” is enabled.
4. After saving, the app publishes the discovery config and shows “Entity created” when HA is detected as subscribed/online (best-effort).

If MQTT is skipped, the system remains usable; HA MQTT setup can be completed later from Settings.

### Settings (app)
Add/update a “Home Assistant” (or “Integrations”) section:
- Enabled toggle
- MQTT connection settings
- **Alarm entity name** (editable)
- Checkbox (default checked): **Also rename in Home Assistant**
- Entity status (created/online/offline), last seen timestamp, last error
- “Re-publish discovery config” action (fixes HA discovery drift)

### Settings (HA)
When MQTT is configured:
- The entity appears under `alarm_control_panel.*` with a stable object id (entity_id should stay stable even if the friendly name changes).
- The name initially comes from the app (from MQTT discovery config).
- v1 policy: if “Also rename in Home Assistant” is checked, updating the name in the app re-publishes discovery config with the new name.

## Identity and rename mechanics

### Recommended identifiers
MQTT discovery uses a stable object id; HA assigns an entity_id derived from it:
- **Discovery object id**: `latchpoint_alarm` (stable)
- **Entity id (HA)**: typically `alarm_control_panel.latchpoint_alarm` (stable)

Do not rely on entity_id drift; if HA entity is deleted, re-publishing discovery recreates it.

### Renaming from the app
When the user updates “Alarm entity name” in the app:
1. Update app settings (`entity_name`).
2. If “Also rename in Home Assistant” is checked, re-publish MQTT discovery config with the updated `name`.
3. If re-publish fails (broker offline/auth), keep app setting updated and show “Pending rename” with the error.

## Data model (app)
Define a single-instance settings block (no profiles):

`home_assistant_alarm_entity` (JSON)
```json
{
  "enabled": false,
  "entity_name": "Home Alarm",
  "also_rename_in_home_assistant": true,
  "ha_entity_id": "alarm_control_panel.latchpoint_alarm",
  "last_seen_at": null,
  "last_error": null
}
```

MQTT connection settings:
- `mqtt_connection`: `{ "host": "...", "port": 1883, "username": "...", "password": "...", "use_tls": false }`

## App API surface
Thin views + use cases (per `docs/adr/0005-thin-views-and-use-cases.md`):
- `GET /api/alarm/home-assistant/status/` (MQTT connection + entity publish status)
- `POST /api/alarm/home-assistant/test/` (test MQTT connection; optional)
- `POST /api/alarm/home-assistant/publish-discovery/` (re-publish discovery config)
- `PATCH /api/alarm/home-assistant/entity-name/` (update name; optionally re-publish discovery)

## MQTT topic design
Choose one stable base topic per app instance:
- Discovery: `homeassistant/alarm_control_panel/latchpoint_alarm/config`
- State: `latchpoint_alarm/alarm/state`
- Command: `latchpoint_alarm/alarm/command`
- Availability (optional): `latchpoint_alarm/alarm/availability`

Discovery payload should:
- Set `name` from app setting
- Provide `state_topic`, `command_topic`, and (recommended) `availability_topic`
- Use a `command_template` that includes both action and code in JSON, so the app can validate user-entered codes

## Commands + “HA user must enter alarm code”
Requirement: HA user must enter the alarm code for disarm.

Approach:
- Configure the MQTT alarm entity so HA always prompts for a code, and publishes commands including the code (via `command_template`).
- This app validates the code using the same rules as the normal disarm endpoint and rejects invalid codes.

## Onboarding flow details

### Happy path
1. User completes app onboarding, enables HA, enters desired alarm name.
2. User configures MQTT in HA (once) and enters MQTT broker details in the app.
3. App publishes MQTT discovery config; HA creates `alarm_control_panel.latchpoint_alarm`.
4. App publishes state updates; HA UI reflects them.
5. User arms/disarms from HA; HA sends command (with code); app validates and transitions.

### Entity not found
If HA doesn’t show the entity:
- Verify HA MQTT integration is connected and discovery is enabled.
- Verify broker connection details in the app.
- Use “Re-publish discovery config”.

## Security + safety
- Never log MQTT passwords or command payload codes.
- Restrict MQTT settings and rename actions to admins.
- Keep code validation identical to the app’s standard keypad/API path.

## Testing plan
Backend:
- Unit tests for discovery payload generation (stable topics/object id; name handling).
- Unit tests for rename flow: checkbox on/off; broker failure → pending error state.
- Unit tests for MQTT command handling: valid vs invalid code; correct transition calls.
- API tests verifying only admins can edit MQTT settings/rename.

## Migration / rollout
If prior installs used webhook mirroring or “sync existing entity”:
- Keep old settings keys readable for one release; auto-migrate to `home_assistant_alarm_entity`.
- UI notice: “HA integration model changed; MQTT is now used to create the HA alarm entity.”

## Acceptance criteria
- Fresh install onboarding can end with a working `alarm_control_panel` entity in HA that mirrors state and can arm/disarm (within defined safety constraints).
- App Settings allow renaming the alarm entity and HA reflects the new name quickly (or shows a clear pending/error status).
- If HA is offline, the app remains usable and surfaces HA status clearly.

## Implementation tasks (suggested order)
1. Define singleton settings schema for `home_assistant_alarm_entity` + `mqtt_connection`.
2. Implement MQTT client/service: publish discovery + publish state + subscribe to command topic.
3. Add onboarding step + settings UI (entity name, “also rename in HA” checkbox, MQTT config).
4. Wire MQTT command handling to existing alarm arm/disarm use cases (disarm requires code).
5. Add end-user docs for HA MQTT prerequisites + troubleshooting.
