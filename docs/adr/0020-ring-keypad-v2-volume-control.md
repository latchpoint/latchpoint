# ADR 0020: Ring Keypad v2 Volume Control

## Status
Proposed

## Context
Users want to control the audible volume (beeps/tones) of a Ring Keypad v2 from the alarm panel UI.

Constraints and realities:
- This is only feasible when the keypad is paired as a Z-Wave device (e.g., via Z-Wave JS). The Ring cloud integration does not expose keypad speaker volume control.
- “Volume” can mean two things:
  - **App-driven sound volume**: volume used when we instruct the keypad to play a sound (e.g., the existing “Test beep” uses Indicator CC sound property 96 with `property_key=9` volume).
  - **Device speaker volume**: the keypad’s internal speaker level (keypress beeps / general tones), typically controlled by a Z-Wave Configuration parameter (device/firmware dependent).
- This repo already has a dedicated **Control Panels** feature (backend `backend/control_panels/`, frontend `frontend/src/pages/ControlPanelsPage.tsx`) with admin CRUD at `/api/control-panels/`.

We need a first-class, editable per-device setting that:
- Is stored alongside the configured control panel device (`ControlPanelDevice`) and editable in the Control Panels UI.
- Can be applied to the keypad (best-effort) without breaking alarm operation if Z-Wave is unavailable.

## Decision
Implement volume control in two phases, starting with what the system already supports reliably.

### Phase 1 (MVP): App-driven keypad sound volume
Backend:
- Add `beep_volume` (integer, 1–99, default 50) to `control_panels.ControlPanelDevice` for Ring Keypad v2 devices.
- Expose `beep_volume` in `ControlPanelDeviceSerializer` and allow updating it via `PATCH /api/control-panels/<id>/`.
- Apply `device.beep_volume` (best-effort) to all Ring Keypad v2 sound-capable Indicator CC writes we trigger:
  - entry/exit delay countdown tones
  - invalid-code / code-not-accepted tone
  - alarm/triggered indicator sound
  - “Test beep”
- Update `POST /api/control-panels/<id>/test/` to accept optional `{ "volume": <int> }`; if omitted, use `device.beep_volume`.
  - “Test beep” uses the existing Indicator CC sound path in `backend/control_panels/zwave_ring_keypad_v2.py:test_ring_keypad_v2_beep()`.

Frontend:
- In `frontend/src/pages/ControlPanelsPage.tsx`, add a Volume control for Ring Keypad v2 panels:
  - A numeric input or slider bounded to 1–99.
  - “Save” triggers `PATCH /api/control-panels/<id>/` with `{ beepVolume: <n> }` (via `useUpdateControlPanelMutation()`).
  - Volume applies to app-driven keypad sounds (not keypress beeps).
  - “Test beep” uses the saved volume by default (optionally add a temporary override UI later).

### Phase 2 (follow-up): Device speaker volume (Configuration parameter)
Backend:
- Introduce a device-specific mapping for Ring Keypad v2 speaker volume via Z-Wave Configuration CC:
  - Either hardcode the known parameter/value mapping once verified, or support an advanced override (`config_param`, `config_value`) gated behind admin UX.
- Add a gateway/manager method to set configuration parameters (if not already available) and apply on save (best-effort).

Frontend:
- Add an “Advanced” section to configure/apply device speaker volume if Phase 2 is implemented.

Operational behavior (Phase 1):
- Volume affects app-driven keypad sounds only (entry/exit delay, invalid code tone, alarm indicator, “Test beep”). It does not change keypress beep volume on the device.
- If Z-Wave JS is disconnected or the node is missing, “Test beep” continues to return an error and sets `last_error` (current behavior).

## Alternatives Considered
- **Do nothing / document manual Z-Wave config only**
  - Simple, but doesn’t meet the “single control panel UI” goal and is easy to misconfigure.
- **Store volume only in Z-Wave JS / HA UI (out of band)**
  - Avoids backend changes, but creates drift and breaks portability of profiles.
- **Implement a generic “Z-Wave config parameter editor”**
  - Powerful, but too broad for the immediate need and increases foot-gun risk. Could be a future enhancement after this focused feature.

## Consequences
- Phase 1 is low-risk and uses an existing, already-tested Z-Wave value write path.
- Phase 1 does not satisfy “device speaker volume” expectations; UI copy must be explicit (“Test beep volume” vs “Keypad speaker volume”).
- Phase 2 will require expanding the Z-Wave gateway surface area and carefully handling device/firmware variability.

## Todos
### Implementation plan (Phase 1)
- DB: add `beep_volume` field + migration on `backend/control_panels/models.py`.
- Backend API:
  - `backend/control_panels/serializers.py`: include `beep_volume` in `ControlPanelDeviceSerializer` and `ControlPanelDeviceUpdateSerializer` (validate 1–99).
  - `backend/control_panels/views.py`: allow patching `beep_volume`; update test endpoint to accept optional `volume` (validate 1–99) and default to `device.beep_volume`.
- Ring Keypad v2 integration:
  - `backend/control_panels/zwave_ring_keypad_v2.py`: apply `device.beep_volume` to sound-capable indicator writes (best-effort).
- Frontend:
  - `frontend/src/types/*`: add `beepVolume` to the ControlPanel device type + update payload types.
  - `frontend/src/pages/ControlPanelsPage.tsx`: render and persist the volume control for Ring Keypad v2 devices.
- Tests:
  - `backend/control_panels/tests/test_control_panels_api.py`: add test for patch validation and that test-beep uses saved volume (assert gateway `set_value` called with `property_key=9` and correct `value`).
  - `backend/control_panels/tests/test_ring_keypad_v2.py`: assert that entry/exit delay and invalid-code indicators also set `property_key=9` volume.

### Acceptance criteria (Phase 1)
- Admin can set and persist volume per Ring Keypad v2 control panel.
- App-triggered keypad sounds (including “Test beep”) use the saved volume and still work with the existing Z-Wave node-presence checks.
- Invalid volumes return a clear 400 with field-level errors; no 500s.

### Follow-up (Phase 2)
- Verify the Ring Keypad v2 “speaker volume” Z-Wave parameter mapping and implement it behind an explicit “speaker volume” setting with robust error reporting.
