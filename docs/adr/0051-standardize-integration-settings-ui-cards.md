# ADR 0051: Standardize Integration Settings UI Cards

## Status
Implemented

## Context
Integration settings tabs have grown organically and now vary in structure and UX:
- Some tabs combine status, enable, and connection fields in one card (e.g., Z-Wave JS).
- Some tabs place actions inconsistently (Save/Reset/Refresh/Test/Sync).
- “Extra” integration features (event viewers, derived entities, sub-features) are mixed into the same form, making it harder to scan and harder to reuse patterns.

This causes recurring problems:
- Users must relearn each integration page (where to enable, how to see connection state, where to save).
- Inconsistent action placement increases accidental edits (e.g., “Test” vs “Save” placement).
- Repeated UI logic (status pills, draft reset/save affordances) increases maintenance cost.

We already have the building blocks:
- Routed settings tabs + per-tab save patterns (ADR 0016).
- A standardized integration status model (enabled/connected/lastError) (ADR 0042).

## Decision
All integration settings tabs will adopt a consistent, card-based layout with a fixed ordering and responsibilities.

### Example layout (markdown)
```text
Settings › Integrations › <Integration>

[Card: <Integration>]
  Title: <Integration name>
  Subtitle: <What this connects to>
  Enable: [toggle]
  Status: [Enabled/Disabled pill] [Connected/Disconnected pill] [Last error (optional)]
  Actions (page-level): [Refresh] [Reset] [Save]
  Actions (common ops, optional): [Test Connection] [Sync Entities] [Publish Discovery] [...]

[Card: Connection / Setup]
  Fields:
    - URL / Host
    - Port
    - Protocol (if applicable)
    - Token / Password (if applicable)
    - Timeouts / Retry (if applicable)
  Notes:
    - Connection-adjacent actions still live in the Overview card for consistency (e.g., Test Connection).
    - This card stays focused on configuration fields only.

[Card: <Feature 1>]
  <Feature-specific content + actions>

[Card: <Feature 2>]
  <Feature-specific content + actions>
```

Example: Home Assistant tab
```text
[Card: Home Assistant]
  Enable: [toggle]
  Status: [...]
  Actions: [Refresh] [Reset] [Save] [Test Connection]

[Card: Connection / Setup]
  Fields: Base URL, Long-Lived Access Token, Timeouts

[Card: MQTT Alarm Entity]
  Content: status + settings + discovery controls
  Actions: [Publish Discovery]
```

### Card 1: Overview / Controls (always first)
The top card is *not* a settings form. It is the “control surface” for the integration tab and contains:
- Title + subtitle (integration name + what it connects to).
- Enable toggle (if the integration supports being enabled/disabled).
- Connection state (status pills: enabled/connected/last error).
- Actions:
  - Primary (page-level): `Save`, `Reset`, `Refresh` (and optionally `Reconnect` when appropriate).
  - Common ops (optional, integration-dependent): `Test Connection`, `Sync Entities`, `Publish Discovery`, etc.

Rules:
- Actions apply to the whole tab draft, not just a specific card.
- Status is visible even when settings are loading.
- The enable toggle lives here (not inside connection fields).

### Card 2: Connection / Setup Settings (always second)
This card contains only the configuration fields required to establish a connection:
- Host/URL, port, protocol, tokens/passwords, timeouts/retry settings, etc.
- Field-level help and validation.

Rules:
- Avoid placing primary page actions here (Save/Reset/Refresh live in Card 1).
- “Connection-adjacent” ops (e.g., `Test Connection`) should live in Card 1 for consistent placement across integrations.

### Card 3+: Integration Features / Tools (optional, below)
Any additional integration functionality appears in separate cards below setup:
- Frigate: events/detections viewers, retention controls, debug tools.
- Home Assistant: MQTT alarm entity discovery/settings, notify services tooling.
- Zigbee2MQTT / Z-Wave JS: entity sync, mapping tools, “set value” helpers, etc.

Rules:
- Each feature gets its own card with its own secondary actions (e.g., `Sync Entities`, `Publish Discovery`).
- Avoid adding feature-specific fields to the connection/setup card.

### Implementation notes (frontend)
- Introduce shared components under `frontend/src/features/integrations/components/`:
  - `IntegrationOverviewCard` (title/subtitle, enable toggle, `ConnectionStatusPills`, Save/Reset/Refresh slot).
  - `IntegrationConnectionCard` (layout wrapper for connection/setup fields).
  - Optional helpers for consistent action groups and skeleton/loading states.
- Refactor existing integration tabs to use this structure, starting with Z-Wave JS (as the reference UX) but splitting it into Overview + Connection cards.

## Alternatives Considered
- Keep each integration tab custom.
  - Pros: fastest short-term; no refactors.
  - Cons: inconsistent UX; duplicated logic; scales poorly as integrations/features grow.

- Standardize within a single “mega card” per tab.
  - Pros: minimal component creation.
  - Cons: still mixes concerns; harder to scan; extra features keep bloating the main form.

- Use nested sub-routes per integration (e.g., `/settings/zwavejs/connection`, `/settings/zwavejs/tools`).
  - Pros: strong separation and deep-linking.
  - Cons: heavier routing complexity; unnecessary for current scope.

## Consequences
- Consistent mental model for users across all integration tabs.
- Clear separation between “control + status” and “setup fields”.
- Enables shared components and reduces duplicated UI logic.
- Requires refactors to existing tabs (starting with Z-Wave JS) and coordination to keep action semantics consistent.

## Todos
- Create shared integration settings UI components (`IntegrationOverviewCard`, `IntegrationConnectionCard`).
- Refactor `Z-Wave JS`, `MQTT`, `Home Assistant`, `Zigbee2MQTT`, and `Frigate` tabs to follow the card ordering.
- Move integration-specific “extra features” into their own cards (e.g., Frigate event viewer; HA MQTT alarm entity).
- Add a lightweight checklist for new integrations: Overview card + Connection card + optional Feature cards.
