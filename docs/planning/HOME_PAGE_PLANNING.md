# Home Page (Dashboard) Planning

## Goal
Define the logged-in “Home” page (currently `frontend/src/pages/DashboardPage.tsx`) as the primary operational dashboard for arming/disarming, situational awareness, and fast navigation.

## Scope (Phase 1)
- Alarm status + arm/disarm controls (existing `AlarmPanel`).
- “At a glance” zone overview (open/triggered/bypassed).
- Recent activity preview (reuse existing recent events feed).
- System connectivity/health (WebSocket + backend/HA reachability signals).
- Quick navigation to core areas: Zones, Events, Codes, Settings.

Out of scope: full automation builder, deep analytics, notifications inbox, HA device/entity management UI.

## Primary Users + Role Considerations
- **Admin**: sees system health details + management links (codes/settings).
- **Resident**: sees core alarm controls + zone/activity.
- **Guest/Service**: can arm/disarm if allowed; should see only what’s necessary (no admin controls).

Assumption: role-based gating happens server-side and is mirrored in the UI by hiding/disabling links/actions.

## Page Outcomes (What “success” looks like)
- A user can confirm current alarm state in <2 seconds.
- A user can arm/disarm with minimal taps (and a clear code flow).
- A user can immediately tell if any zones are open/triggering/bypassed.
- A user can see the last few events and jump to the full Events page.
- Connectivity issues are visible (offline mode doesn’t feel “broken”).

## Layout and Information Architecture

### Desktop (≥ lg)
Two-column layout:
- **Left (primary)**: Alarm control card (state + countdown + actions).
- **Right (secondary)**:
  - Zone summary card
  - System status card
  - Quick links card (or small tiles)
- **Full width below**: Recent activity preview (or keep it inside AlarmPanel for MVP).

### Mobile (< lg)
Single column, stacked:
1) Alarm controls
2) Zone summary
3) Recent activity
4) System status
5) Quick links

## Widgets (MVP)

### 1) Alarm Control
- Use `frontend/src/components/alarm/AlarmPanel.tsx`.
- Ensure initial fetch/connect happens on page mount (or globally via app shell) so the panel has state quickly.
- Follow-up TODO: replace the inline keypad “modal” in `AlarmPanel` with a shared Dialog component (shadcn/ui) for focus trapping and accessibility.

### 2) Zone Summary
Purpose: make it obvious if arming is safe/expected.

Display (suggested):
- Counts: total zones, open zones, bypassed zones, alarmed/triggered zones.
- Top 3 “attention” zones listed by severity:
  - Triggered > Open > Bypassed
- Actions:
  - “View all zones” → Zones page
  - Optional: quick bypass/unbypass (only if role permits)

Data: `useAlarmStore().zones` and zone fields required for open/bypassed/triggered calculations.

### 3) Recent Activity Preview
- Reuse `useAlarmStore().recentEvents` and `frontend/src/components/alarm/AlarmHistory.tsx`.
- Show 5–10 entries with timestamps + event type.
- “View all events” → Events page.

### 4) System Status
MVP indicators:
- WebSocket: reuse header status (`wsStatus`) but show a more descriptive card on the Home page when not connected.
- Backend health: lightweight ping endpoint (if/when available) or infer from recent successful API calls.
- Home Assistant connectivity: explicit backend-provided status (preferred) rather than browser-side HA checks.

### 5) Quick Links
Small card/tiles:
- Zones
- Events
- Codes
- Settings

Role gating:
- Hide Codes/Settings for non-admin if not allowed.

## Data + State Requirements

### Existing client state
- Alarm state, countdown, recent events, zones, wsStatus are already in `frontend/src/stores/alarmStore.ts`.

### What the Home page should trigger
- Ensure `fetchAlarmState`, `fetchZones`, and `fetchRecentEvents` are called if the app isn’t already doing this elsewhere.
- Ensure `connectWebSocket()` is called once per session (prefer app-level, not per-page).

### Missing (likely) backend fields for a good dashboard
- Zone “open”/“fault” signal (per-sensor status) or computed zone status.
- A backend “system status” endpoint that includes HA connection state + last sync time.

## Loading / Error / Offline States
- While loading: show skeleton cards or minimal placeholders (avoid layout shift).
- If WebSocket is offline: page still works via polling/manual refresh, but show a visible “Offline” state and disable actions that require live state if needed.
- Error surfaces:
  - Alarm control errors stay local to `AlarmPanel`.
  - Widget-level errors should not break the whole page.

## Accessibility / UX Requirements
- Keyboard + screen-reader friendly arming/disarming flow:
  - Focus trapping and “Escape to close” on keypad modal.
  - Clear labels for state, countdown, and primary action.
- Color is not the only indicator (badges + text).
- Mobile-first tap targets (min 44px).

## Implementation Plan

### Phase 1A (Compose the dashboard)
- Replace placeholder content in `frontend/src/pages/DashboardPage.tsx` with a responsive grid and mount `AlarmPanel`.
- Add “Quick Links” card (static navigation).

### Phase 1B (Zone summary)
- Create a `ZoneSummary` component (new file under `frontend/src/components/zones/` or `frontend/src/components/dashboard/`).
- Use existing zone store data + add minimal styling and empty-state messaging.

### Phase 1C (System status)
- Create a `SystemStatusCard` that reads `wsStatus` (and later backend/HA status when available).

### Phase 1D (Polish)
- Replace inline keypad modal with shared Dialog.
- Add loading skeletons and basic empty/error states.

## Acceptance Criteria (Phase 1)
- Home page displays the current alarm state and allows arming/disarming.
- Zone summary shows counts and a clear “attention” list when something is open/triggered/bypassed.
- Recent activity preview renders and links to the Events page.
- Offline/WebSocket disconnect state is visible and doesn’t crash the UI.
- Mobile layout is usable without horizontal scrolling.

## Open Questions / TODOs
- What is the canonical zone status model (zone-level vs sensor-level open/triggered)?
- Which roles can bypass zones or view detailed zone/sensor information?
- Do we want Home page customization (reorder/hide widgets) in a later phase?
- Should arming be blocked when open zones exist, or just warned?
