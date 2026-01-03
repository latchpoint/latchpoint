# Control Panels

This project can ingest events from physical “control panels” (keypads) and drive the alarm state machine using the same PIN codes managed in the app.

## Ring Keypad v2 (Z-Wave JS)

Requirements:
- Z-Wave JS integration configured and connected (`Settings → Z-Wave JS`)
- A Ring Keypad v2 paired with S2 (recommended)

Setup:
1. Go to `Settings → Control Panels`.
2. Add a “Ring Keypad v2 (Z-Wave JS)” device.
3. Enter the keypad `home_id` + `node_id` (you can read `home_id` from `/api/alarm/zwavejs/status/`).
4. Map keypad “Arm Home” and “Arm Away” to your desired alarm states.

Behavior:
- Disarm always requires a valid code.
- Arm respects the existing `code_arm_required` setting (unless a code is provided).
- Alarm state changes are mirrored back to the keypad via Indicator CC (best-effort).

## Future work (ideas / backlog)

### Status UX
- Show `last_seen_at` and `last_error` in the Control Panels UI list, with “online recently” heuristics (e.g. seen in last N minutes).
- Add a “Clear error” action (sets `last_error=""`) and/or auto-clear on successful test event.

Acceptance criteria:
- UI displays both fields for each panel.
- “Online recently” is derived purely from `last_seen_at` and a configurable cutoff.

### Edit panel assignment
- Allow updating a panel’s Z-Wave `home_id`/`node_id` from the UI (instead of delete+recreate).
- Reuse duplicate protections so a node can’t be assigned to two panels.

Acceptance criteria:
- Admin can change `external_id` and the backend rebuilds `external_key` consistently.
- Duplicate assignment returns a clear validation error in the UI.

### Multi-home support
- If multiple Z-Wave “homes” are possible, add an explicit `home_id` selection UX and ensure “already added” detection is unambiguous.

Acceptance criteria:
- Node picker “already added” checks are correct when multiple `home_id`s exist.
- UI makes it obvious which `home_id` is in use for a panel.

### Heartbeat / connectivity
- Add a periodic “ping”/health check for Z-Wave panels (or a polling loop) so online/offline isn’t solely based on keypress events.
- Decide whether to treat “driver ready” as sufficient for “connected” vs. per-node reachability.

Acceptance criteria:
- Online/offline remains accurate when the keypad is idle (no events) and when Z-Wave JS reconnects.

### Testing improvements
- Expand API tests to cover the edit flow once implemented.
- Add a small integration-style test for the Z-Wave beep path when Z-Wave is disabled/not configured (expected 400).
