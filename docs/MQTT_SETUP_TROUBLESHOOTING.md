# MQTT Setup + Troubleshooting (Home Assistant Alarm Entity)

This app creates a Home Assistant `alarm_control_panel` entity using **Home Assistant’s MQTT integration + MQTT discovery**.

## Prerequisites
- A working MQTT broker (e.g. Mosquitto).
- Home Assistant has the **MQTT** integration configured and connected to that broker.
- MQTT discovery is enabled (default in HA when MQTT is set up).

## App-side setup
1. Go to `Settings` → `Home Assistant (MQTT)` → `Configure MQTT`.
2. Fill in:
   - broker host + port
   - username/password (if required)
   - TLS (optional)
3. Click `Test Connection`.
4. Click `Save`.
5. Enable “Create Home Assistant alarm entity” and set the name.
6. Click `Publish Discovery`.

## What Home Assistant should create
An entity:
- `alarm_control_panel.latchpoint_alarm`

If it doesn’t appear, see troubleshooting below.

## Topics used
- Discovery: `homeassistant/alarm_control_panel/latchpoint_alarm/config` (retained)
- State: `latchpoint_alarm/alarm/state` (retained)
- Availability: `latchpoint_alarm/alarm/availability` (retained)
- Command: `latchpoint_alarm/alarm/command` (published by HA on arm/disarm)
- Error: `latchpoint_alarm/alarm/error` (optional; published by the app when rejecting commands)

## State values
The app publishes these states (same strings as HA alarm states):
- `disarmed`
- `arming`
- `pending`
- `triggered`
- `armed_home`
- `armed_away`
- `armed_night`
- `armed_vacation`

## Command behavior (code required)
- Disarm always requires a code.
- Arming requires a code only if the app setting “Code required to arm” is enabled.

If HA sends an invalid/missing code, the command is rejected and the app publishes to:
- `latchpoint_alarm/alarm/error` with JSON `{ "action": "...", "error": "..." }`

## Troubleshooting

### Entity never appears in HA
- Confirm HA MQTT integration is connected to the same broker the app uses.
- Confirm the app shows MQTT status as connected (`/setup/mqtt` page).
- Click `Publish Discovery` again.
- Check the broker for retained discovery config on:
  - `homeassistant/alarm_control_panel/latchpoint_alarm/config`

### Entity appears but never updates
- Confirm the app publishes state updates:
  - `latchpoint_alarm/alarm/state`
  - `latchpoint_alarm/alarm/availability` should be `online`
- Trigger a state change in the app and watch if the state topic changes.

### HA can arm but can’t disarm
- Disarm requires a valid code.
- Ensure at least one alarm code exists in the app.
- Check `latchpoint_alarm/alarm/error` for `Invalid code` or `Code required`.

### MQTT shows connected but HA still shows “unavailable”
- Ensure HA is receiving availability:
  - `latchpoint_alarm/alarm/availability` should be `online`
- If HA restarts, click `Publish Discovery` again (retained should persist, but this is a quick sanity check).
