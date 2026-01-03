# Live Integration Status in UI (WebSocket-first)

## Summary

Today the UI polls most integration “status” endpoints (MQTT/Z-Wave/Zigbee2MQTT/Frigate) on an interval, while Home Assistant status is fetched on-demand. This doc proposes making these statuses “live” in the UI (System Status card + each integration’s Settings tab) by pushing status updates through the existing authenticated alarm WebSocket (`/ws/alarm/`) and using them to update React Query caches.

This keeps the UI responsive, reduces background HTTP polling, and creates a single real-time channel for “system state”.

## Goals

- Integration status cards update within ~1s of a real state change (connect/disconnect/error, ingest/sync events, enable/disable).
- Prefer push over polling (WebSocket-first) with a safe HTTP fallback.
- Reuse the existing WebSocket infrastructure (`backend/alarm/consumers.py`, `frontend/src/services/websocket.ts`, `AlarmRealtimeProvider`).
- Avoid leaking secrets (tokens/passwords) and keep payloads small.
- Only show boolean state in UI (`connected` / `available` / `reachable`), even if we include additional fields internally to compute those booleans correctly.
- “Zigbee2MQTT connected” means **Z2M is alive** (recently observed Z2M traffic), not merely “MQTT broker is connected”.

## Non-goals

- Streaming large data (Z-Wave node state, full entity lists, Frigate detections) over WebSocket.
- Replacing all HTTP reads/writes for integration settings.
- Perfect real-time HA availability without any background work (HA is not a long-lived connection today).

## Current State (as of now)

- WebSocket:
  - `/ws/alarm/` authenticates and broadcasts `alarm_state` via `alarm.websocket.broadcast_alarm_state()`.
  - Frontend listens in `frontend/src/components/providers/AlarmRealtimeProvider.tsx` and updates React Query caches for alarm state/events/countdowns.
- Integrations status in UI:
  - `SystemStatusCard` reads multiple `use*StatusQuery()` hooks.
  - MQTT/Z-Wave/Zigbee2MQTT/Frigate hooks poll via `refetchInterval: FIVE_SECONDS_MS`.
  - Home Assistant status is fetched without polling and refreshed via manual invalidation.

## Proposed Approach

### 1) Add a “system/integrations status” WebSocket message

Create a new WS message type (name bikeshed: `system_status` or `integrations_status`) delivered on:

- WS connect (initial snapshot, alongside `alarm_state`).
- Any detected status change (edge-triggered).
- Any relevant config change (e.g. settings profile activation / integration enabled flags).

Recommended: **single aggregated message** to keep the client simple and reduce fan-out.

Example message shape:

```json
{
  "type": "system_status",
  "timestamp": "2025-01-01T12:00:00Z",
  "sequence": 123,
  "payload": {
    "home_assistant": { "configured": true, "reachable": false },
    "mqtt": { "configured": true, "enabled": true, "connected": true },
    "zwavejs": { "configured": true, "enabled": true, "connected": false },
    "zigbee2mqtt": { "enabled": true, "connected": false },
    "frigate": { "enabled": true, "available": false }
  }
}
```

Notes:
- Payload is intentionally “UI-minimal” (booleans only).
- Use snake_case on the backend; frontend WS client already camelCases keys deeply.
- Never include secrets (HA token, MQTT password, etc.). Only status/metadata already returned by status endpoints.

### 2) Backend: broadcast on change (push) + seed on connect

#### Message building + broadcast

- Add a builder (similar to `alarm.websocket.build_alarm_state_message`) for the new status message.
- Add `broadcast_system_status()` that sends to the existing `"alarm"` WS group.

Suggested location: `backend/alarm/websocket.py` (or a sibling module if it grows).

#### Status snapshot source of truth

Prefer reusing the same functions used by HTTP endpoints, but project them down to booleans:

- MQTT: `transports_mqtt.manager.mqtt_connection_manager.get_status().as_dict()`
- Z-Wave JS: `integrations_zwavejs.manager.zwavejs_connection_manager.get_status().as_dict()` (or equivalent)
- Zigbee2MQTT: maintain a “last seen Z2M message” timestamp in a small status store (cache), updated whenever we process any Z2M-ingest MQTT message; define `connected = now - last_seen <= grace_window_seconds`
- Frigate: `integrations_frigate.runtime.is_available()` + ingest cache fields + MQTT status
- Home Assistant: best-effort cached status (see next section)

#### Trigger points (“when do we broadcast?”)

1) **MQTT connection manager**
   - On connect / disconnect / error updates inside `backend/transports_mqtt/manager.py`.
   - Add a lightweight internal hook, e.g. `_maybe_emit_status_change(prev, next)`; if changed, call broadcaster.

2) **Z-Wave JS connection manager**
   - On connect / disconnect / driver_ready / error updates in `backend/integrations_zwavejs/manager.py`.
   - Same “compare previous vs next” + broadcast.

3) **Zigbee2MQTT**
   - On `mark_sync()` / `mark_error()` updates in `backend/integrations_zigbee2mqtt/status_store.py`.
   - Optionally also broadcast on `apply_runtime_settings_from_active_profile()` when enabling/disabling.

4) **Frigate**
   - On `mark_ingest()` / `mark_error()` updates in `backend/integrations_frigate/runtime.py`.
   - Optionally broadcast on `apply_runtime_settings_from_active_profile()`.

5) **Settings profile changes**
   - There is already a `settings_profile_changed` signal (`backend/alarm/signals.py`).
    - Add a receiver that broadcasts a fresh `system_status` snapshot on activation/update (so UI reflects enable/disable quickly).

6) **Time-derived availability (important for “available” booleans)**
   - Some booleans are time-based (e.g. Frigate `available` can flip false after `availability_grace_seconds` with no new events).
   - Zigbee2MQTT “alive” is also time-based (can become disconnected without a local event).
   - To make these correct without frontend polling, add a lightweight periodic “status tick” in the backend (e.g. every 5–10s) that:
     - recomputes the projected booleans (`frigate.available`, `zigbee2mqtt.connected` if derived),
     - broadcasts only when values change.
   - This is backend-internal work; the frontend remains WS-only.

#### Home Assistant status (special case)

HA status today is computed via a short HTTP/client probe when the status endpoint is called, not via a long-lived manager.

Two viable options:

**Option A (recommended if you want “reachable” live-ish): background HA status watcher**
- Maintain a cached “last known HA status” in Django cache.
- Run a single lightweight background loop (thread) that:
  - wakes every N seconds (e.g. 15–30s),
  - reads active profile HA settings,
  - calls `integrations_home_assistant.api.get_status(timeout_seconds=2)`,
  - updates cache and broadcasts only when the result changes.
- Start it from the HA app config on Django startup (similar to other runtimes).

**Option B (lower-effort): update HA only on-demand**
- Only push MQTT/Z-Wave/Z2M/Frigate through WS.
- HA `reachable` only updates when the HA status endpoint is called (e.g. manual refresh / Settings tab open).

### 3) Frontend: consume message and update React Query caches

#### Types + validation

- Extend `frontend/src/types/alarm.ts` WebSocket union with `type: 'system_status'`.
- Add a runtime guard in `frontend/src/lib/typeGuards.ts` (parallel to `isAlarmStatePayload`, etc.).

#### Cache writes

In `frontend/src/components/providers/AlarmRealtimeProvider.tsx`, handle the new message by calling:

- `queryClient.setQueryData(queryKeys.mqtt.status, payload.mqtt)`
- `queryClient.setQueryData(queryKeys.zwavejs.status, payload.zwavejs)`
- `queryClient.setQueryData(queryKeys.zigbee2mqtt.status, payload.zigbee2mqtt)`
- `queryClient.setQueryData(queryKeys.frigate.status, payload.frigate)`
- `queryClient.setQueryData(queryKeys.homeAssistant.status, payload.homeAssistant)`

This keeps existing UI components unchanged because they already read these query keys.
It also automatically updates the corresponding Settings tabs because they read the same status query keys.

#### Reduce polling (with safe fallback)

Phased approach:

1) Keep current polling while WS support lands, but prefer WS data when present.
2) Remove the 5s `refetchInterval` for statuses covered by WS (WS-only).
3) Keep a “Refresh” button (already exists in `SystemStatusCard`) as the manual fallback.

## Rollout Plan (incremental)

### Phase 1: Foundation
- Add `system_status` WS message type + initial snapshot on connect.
- Populate MQTT + Z-Wave only (best signal-to-effort; real managers exist).
- Frontend: receive and write into `queryKeys.mqtt.status` and `queryKeys.zwavejs.status`.

### Phase 2: Zigbee2MQTT + Frigate
- Emit broadcasts from Z2M `status_store` and Frigate `mark_*` helpers.
- Frontend: update `queryKeys.zigbee2mqtt.status` + `queryKeys.frigate.status`.

### Phase 3: Home Assistant (optional but desired)
- Implement HA status watcher (Option A) and broadcast on change.
- Frontend: update `queryKeys.homeAssistant.status`.

### Phase 4: Remove polling
- Turn off 5s polling for statuses fully covered by WS.
- Keep a slow periodic refetch as belt-and-suspenders if desired.

## Testing Strategy

Backend:
- Extend `backend/alarm/tests/test_websocket.py` to assert `system_status` is sent on connect.
- Add targeted tests that trigger a status change and confirm a broadcast (e.g., force MQTT manager state change via a test helper or by calling internal hooks).
- If HA watcher is added, test that cache-change triggers a broadcast (unit-test the “diff + broadcast” function; avoid real network).

Frontend:
- Type-level compile checks (new WS message union).
- Unit tests (if present) for `isSystemStatusPayload` guard.
- Manual: open dashboard, toggle integration settings and observe the `SystemStatusCard` update without clicking refresh.

## Risks / Mitigations

- **Broadcast storms** (rapid connect/disconnect loops): debounce/coalesce in broadcaster (e.g. “emit at most once per 250ms per integration”).
- **Circular imports** (managers importing alarm websocket): keep broadcaster in a small module and import lazily inside functions.
- **Client desync**: send initial `system_status` snapshot on connect, and keep manual refresh.
- **HA watcher complexity**: start with Option B and revisit if needed.

## Open Questions

- Message naming: `system_status` vs `integrations_status` vs reuse existing `health` message type.
- Do we want per-integration messages (more granular) or a single aggregated payload (simpler)?
- Should statuses be per-active-profile only (likely) or per-user (unlikely)?
