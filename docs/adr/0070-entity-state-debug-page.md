# ADR 0070: Entity State Debug Page

## Status
Proposed

## Context
When defining rules in LatchPoint, users need to know the exact state values that Home Assistant entities report. For example, a user creating a rule for `light.lamp` needs to know whether the state is `"on"` / `"off"`, what attributes are available, and what values those attributes hold. Currently, there is no way to inspect raw entity state within LatchPoint — users must switch to the Home Assistant UI or developer tools to look up this information.

This friction slows down rule authoring and increases the chance of misconfigured conditions (e.g., comparing against `"On"` instead of `"on"`).

Additionally, as the system grows in complexity (multiple integration sources, synthetic entities, scheduled tasks, WebSocket connections), there will be a need for other diagnostic tools. A dedicated debug/diagnostics area provides a natural home for these.

## Decision
We will add a **Debug** page to the frontend, initially containing an **Entity State Inspector** tool. The page will be designed as an extensible container so future debug tools can be added alongside it.

### Entity State Inspector

**Core functionality:**
1. **Entity picker** — searchable dropdown listing all known entities, filterable by domain and source
2. **Live state display** — shows the selected entity's current `last_state`, `attributes` (full JSON), `domain`, attribute-derived fields like `device_class` (`attributes.device_class`) and `unit_of_measurement` (`attributes.unit_of_measurement`), `source`, `last_changed`, and `last_seen`
3. **Real-time updates** — state refreshes automatically via WebSocket `entity_sync` messages so users see changes as they happen (e.g., toggling a light and watching the state flip)

**UI design:**
- Entity picker at the top with search and optional domain/source filters
- Below the picker, a structured read-only panel displaying entity state and attributes
- Attributes rendered as a formatted JSON tree (collapsible for large payloads)
- Visual indicator when a state value changes (brief highlight/flash)
- Timestamp display for `last_changed` and `last_seen` in relative format ("2 seconds ago")

**Data flow:**
- Entity list sourced from `GET /api/alarm/entities/` via `useEntitiesQuery()` (existing)
- Initial entity detail loaded from entity list cache or a dedicated endpoint
- Live updates via existing WebSocket `entity_sync` messages on the `alarm` channel
- Frontend filters WebSocket updates to only display changes for the selected entity

### Extensible Debug Page Structure

The debug page will use a tabbed or sectioned layout:
- **Entity State Inspector** (this ADR) — first tool
- Future tools slot in as additional tabs/sections (e.g., WebSocket connection status, rule evaluation trace, scheduler health)

### Navigation

- Add a "Debug" entry to the sidebar navigation
- Place it in a secondary/utility section (below primary alarm/rules/settings navigation)

## Alternatives Considered

- **Link out to HA developer tools** — zero implementation cost but breaks the workflow; users lose context switching between apps. Doesn't help with synthetic entities or multi-source state.
- **Inline state preview in rule builder** — useful but limited scope; doesn't help with general exploration or future debug tools. Could be added later as a complement.
- **Polling-based refresh** — simpler than WebSocket but adds unnecessary load and latency. WebSocket infrastructure already exists.

## Consequences

- Users can inspect any entity's raw state without leaving LatchPoint
- Rule authoring becomes faster and less error-prone — users see exact values to match against
- Synthetic entities (`__system.alarm_state`, `__frigate.person_detected:*`) become visible and inspectable
- The debug page establishes a pattern for adding future diagnostic tools
- WebSocket `entity_sync` messages get a consumer on the frontend (currently underutilized)
- Minimal backend changes needed — existing entity API and WebSocket broadcasts cover the data requirements

## Todos
- [ ] Create `DebugPage` container component with tabbed/sectioned layout
- [ ] Build `EntityStateInspector` component with entity picker and state display
- [ ] Add entity attribute JSON tree viewer (collapsible)
- [ ] Subscribe to WebSocket `entity_sync` for live state updates on selected entity
- [ ] Add change highlight animation when state values update
- [ ] Add "Debug" entry to sidebar navigation
- [ ] Add route `/debug` to the frontend router
- [ ] Consider adding an inline "Inspect" link from the rule builder entity picker (future enhancement)
