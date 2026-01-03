# ADR 0016: Settings UI as Routed Tabs with Per-Tab Save

## Status
Proposed

## Context
The Settings UI is currently a single page with multiple concerns mixed together:
- Alarm configuration (“general” alarm behavior)
- Integrations (Home Assistant, MQTT, Z-Wave JS)
- Notifications (more types will be added)

This creates recurring problems:
- Hard to deep-link users (and future Setup Wizard steps) to a specific settings area.
- A single “Save” tends to couple unrelated settings and increases accidental changes.
- Adding new integration/notification types increases page complexity and makes ownership unclear.
- It’s harder to evolve backend endpoints/settings registries when the UI assumes one monolithic form.

## Decision
We will split Settings into **routed tabs**, each owning its own state, API calls, validation, and save action.

### Backend ownership model (settings storage vs. settings features)
We will keep **settings persistence** centralized in the alarm domain (the active settings profile + key/value entries), and keep **settings feature ownership** in each Django app:
- The canonical storage remains `AlarmSettingsProfile` + `AlarmSettingsEntry` (alarm domain), so integrations can share a single active profile and so core timing/state machine logic can read settings without cross-app coupling.
- Each Django app (alarm core, HA integration, MQTT transport, Z-Wave JS integration, notifications) owns:
  - its own API endpoints for reading/updating its settings,
  - its own serializers/validation and secret masking/encryption rules,
  - best-effort “apply settings” side effects via the existing signal boundary on profile changes.

Implementation note: setting *definitions* (keys/defaults/metadata) may start centralized but should be moved toward a per-app registration pattern over time so integration apps can declare their own keys without requiring the core alarm app to “know” every integration key.

### Routes / tabs
- `/settings/alarm` (Alarm settings; this is the former “General” tab)
- `/settings/home-assistant` (includes HA connection settings; see ADR 0017)
- `/settings/mqtt`
- `/settings/zwavejs`
- `/settings/notifications`
- `/settings` redirects to `/settings/alarm`

### Per-tab ownership rules
- Each tab is implemented as its own page/component (route entry).
- Each tab has its own **Save** button and only persists the settings it owns.
- Tabs may fetch from shared settings sources, but must send **scoped payloads** (partial updates) to avoid overwriting unrelated settings.
- Cross-tab dependencies must be minimized; if unavoidable, they must be explicit (e.g., “MQTT required for HA-over-MQTT” is surfaced as UI guidance, not implicit coupling).

### Notifications extensibility
The Notifications tab is designed as an extensible container so new notification types can be added without changing routes:
- `/settings/notifications` stays stable.
- New notification types become additional sections within the page (or nested sub-routes later if needed), each with their own enable/config/save behavior.

## Alternatives Considered
- Keep a single Settings page and add in-page tabs (no route changes).
  - Pros: fewer routing changes.
  - Cons: weak deep-linking, larger coupled form, harder future expansion.

- Keep single page but create separate “Save” buttons per section.
  - Pros: less routing work, some decoupling.
  - Cons: still poor deep-linking/refresh behavior; component complexity remains high.

- Make each settings domain a separate top-level page (no tab UI).
  - Pros: simplest routing model.
  - Cons: loses a cohesive “Settings” hub; navigation becomes noisier.

## Consequences
- Better UX: direct links to specific settings, predictable save scope, smaller mental model per tab.
- Clearer ownership: alarm vs integrations vs notifications have explicit boundaries in UI and API calls.
- More routing and component structure: adds some boilerplate and requires consistent navigation patterns.
- Requires backend support for safe partial updates (or carefully constructed payloads) to prevent accidental overwrites.

## Todos
- Implement `/settings/*` routes and tabs navigation, with `/settings` → `/settings/alarm` redirect.
- Split existing Settings UI into per-tab pages with independent form state and per-tab mutations.
- Ensure backend endpoints and/or serializers support partial updates for each tab’s owned fields.
- Update any setup wizard links to target the correct routed tab.
- Add focused tests to ensure saving one tab does not change other settings.
