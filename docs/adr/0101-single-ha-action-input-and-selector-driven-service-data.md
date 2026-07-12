# ADR-0101: Single HA Action Input and Selector-Driven Service Data in the Rules Builder

**Status:** Proposed
**Date:** 2026-07-12
**Author:** Leonardo Merza

## Context

### Background

Home Assistant 2024.8 renamed "service calls" to **actions** and collapsed
the old domain + service pair into a single `action: light.turn_on`
identifier — the HA automation editor presents one searchable action picker,
not two fields. Latchpoint's rules builder still shows the pre-2024.8 shape:
the `ha_call_service` action form renders separate **Domain** and **Service**
text inputs, and service data (brightness, RGB color, transition, …) is a
raw JSON textarea with no structured editing.

Users authoring a rule like "WHEN armed_away triggers → turn the porch light
red" must know the service name by heart, type it into two boxes, and
hand-write `{"rgb_color": [255, 0, 0]}` as JSON.

### Current State

- **The wire format is already merged.** The backend has stored a single
  `action` string since the initial commit:
  `backend/alarm/rules/action_handlers/ha_call_service.py` reads
  `action.get("action")`, validates it contains a `.`, and splits into
  domain/service only at dispatch time. There was never a separate
  domain/service storage shape — **no data migration is needed**.
- **The two inputs are a frontend illusion.** `HaCallServiceFields` in
  `frontend/src/features/rules/queryBuilder/ActionsEditor.tsx` splits the one
  `action` string on the first dot into Domain/Service inputs and re-joins on
  change. The TS type (`frontend/src/types/ruleDefinition.ts`,
  `HaCallServiceAction`) already documents the HA 2024.8+ terminology.
- **Service data is free-form.** Backend validation
  (`backend/alarm/rules/action_schemas.py::_validate_ha_call_service`) only
  requires `data` to be a dict; the frontend edits it as raw JSON with an
  "Invalid JSON" guard.
- **No services catalog is exposed.**
  `backend/integrations_home_assistant/impl.py::list_services` already
  proxies HA's `GET /api/services`, but it is only consumed internally by
  `list_notify_services` (notify domain filter). No API endpoint or frontend
  query exists for the full catalog.
- **HA's REST `/api/services` returns full field metadata.** Verified against
  HA core (`APIServicesView` → `async_services_json` →
  `async_get_all_descriptions`): each service comes back with `name`,
  `description`, `target`, and `fields` — and each field carries a
  **`selector`** definition (`color_rgb`, `number` with min/max/unit,
  `boolean`, `select` with options, …). This is the same metadata HA's own
  editor uses to build its action forms. (The REST API docs' example showing
  a flat list of service names is outdated; Latchpoint's own
  `list_notify_services` already parses `services` as a dict.)
- **No color widget exists.** The frontend has no color input and no color
  library; the only Radix package is `react-slot`. Closest reusable
  primitives: `EntityPicker` (custom searchable listbox, already used for the
  action's target entities), `DatalistInput`, `Select`, and
  `IntegrationSettingsForm`'s type→widget mapping (no color or combobox
  branch).

### Requirements

- One **Action** input (`domain.service`) replacing the Domain/Service pair,
  matching HA 2024.8+ mental model.
- Discoverability: the user should be able to search available services with
  friendly names instead of memorizing identifiers.
- Structured editing for common service data — at minimum an RGB color
  picker for light services — without losing the ability to enter arbitrary
  JSON.
- Existing saved rules must load and round-trip unchanged.
- Degrade gracefully when HA is unreachable (rules must remain editable).

### Constraints

- `alarm/rules/` and `alarm/use_cases/` must NOT import `integrations_*` or
  `transports_*` (enforced import boundary). Any new view lives in
  `integrations_home_assistant`, following the existing
  `HomeAssistantNotifyServicesView` gateway pattern.
- `ha_call_service` is an admin-only action type
  (`ADMIN_ONLY_ACTION_TYPES`); nothing here may widen who can author it.
- Keep `data` free-form on the backend — HA is the authority on which fields
  a service accepts; Latchpoint should not re-validate service data and
  break on HA upgrades.

## Options Considered

The decision has three parts: (A) the action input, (B) the service-data
editor, (C) the color widget.

### A1: Searchable combobox fed by a new services-catalog endpoint (chosen)

**Description:** Expose `impl.list_services` through a new
`GET /api/alarm/home-assistant/services/` endpoint; render an
`EntityPicker`-style searchable combobox listing every `domain.service` with
its friendly name. Free-text entry remains available when the catalog is
empty or HA is unreachable.

**Pros:**
- Discoverable — mirrors the HA 2024.8+ action picker.
- Reuses the proven `EntityPicker` interaction pattern.
- The catalog endpoint also carries the field metadata that powers part (B).

**Cons:**
- New backend endpoint + view + tests.
- Needs HA reachable to populate (mitigated by free-text fallback).

### A2: Datalist autocomplete

**Description:** Same catalog endpoint, but bind it to the existing
`DatalistInput` (native `<datalist>`).

**Pros:** minimal new frontend code.

**Cons:** no friendly names or descriptions; datalist UX is inconsistent
across browsers; still requires the same backend endpoint, so it saves
little.

### A3: Plain merged text input

**Description:** Replace the two boxes with one text input bound directly to
`action`. No autocomplete, no backend work.

**Pros:** smallest possible change; no HA availability dependency.

**Cons:** zero discoverability — typos only caught by the dot check; provides
no field metadata, so part (B) would need a separate mechanism anyway.

### B1: Selector-driven dynamic form (chosen)

**Description:** The catalog endpoint passes through each service's `fields`
with their `selector` definitions. After a service is picked, render one
widget per known selector type: `color_rgb` → color picker, `number` →
numeric input honoring min/max/step/unit, `boolean` → switch, `select` →
dropdown, `text` → text input. Unknown selector types and extra keys fall
back to the existing raw-JSON editor, which stays available as an
"Advanced" section.

**Pros:**
- Works for every service automatically, including future HA integrations —
  no per-service maintenance.
- Exactly how HA's own editor works; consistent with Latchpoint's
  schema-driven UI philosophy (ADR-0079).
- The JSON fallback keeps the full power-user escape hatch.

**Cons:**
- Largest scope: the selector→widget mapper is a new frontend subsystem.
- Depends on HA metadata quality (mitigated by the JSON fallback).

### B2: Curated fields for common services

**Description:** Hardcode field definitions for popular services
(`light.turn_on`: `rgb_color`/`brightness_pct`/`color_temp`; switch, lock,
cover, …). Everything else keeps the JSON textarea.

**Pros:** medium scope; deterministic without HA metadata.

**Cons:** permanent maintenance burden that drifts as HA evolves; uncommon
services get nothing; duplicates data HA already serves.

### B3: JSON textarea + one-off color helper

**Description:** Keep the raw JSON editor as the only surface, add a color
picker button that inserts/updates an `rgb_color` key.

**Pros:** tiny change; no new endpoint.

**Cons:** JSON-first UX remains for everything else; the color button is a
special case, not a pattern to grow.

### C1: react-colorful (chosen)

**Description:** `RgbColorPicker` from
[react-colorful](https://www.npmjs.com/package/react-colorful) — ~2.8 KB
gzipped, zero dependencies, WAI-ARIA compliant, actively maintained (v5.7.0,
mid-2026). Saturation square + hue slider.

**Pros:** de-facto standard, smallest footprint, accessible, touch-friendly.

**Cons:** not a literal color *wheel* (saturation-square style).

### C2: @uiw/react-color-wheel

**Description:** A true hue/saturation wheel (visually like HA's own light
card), installable as a standalone sub-package of the modular
`@uiw/react-color` suite (also actively maintained).

**Pros:** matches the HA frontend wheel aesthetic.

**Cons:** needs two sub-packages (wheel + brightness slider); smaller
community than react-colorful; larger combined footprint.

### C3: Native `<input type="color">`

**Description:** The browser's built-in color dialog; convert hex →
`[r, g, b]`.

**Pros:** zero dependencies.

**Cons:** modal-only, cannot be embedded inline, UX varies wildly by
browser/OS; no wheel.

## Decision

**Chosen: A1 + B1 + C1** — a searchable action combobox backed by a new
services-catalog endpoint, a selector-driven service-data form with a raw-JSON
fallback, and react-colorful for the `color_rgb` widget.

**Rationale:**

- One new endpoint powers both features: the same `GET /api/services` payload
  carries the service list (A) and the per-field selector metadata (B).
  Choosing A3/B2/B3 would save little now and forfeit that leverage.
- B1 is the only option that scales with HA itself — HA already publishes the
  form schema; rendering it is strictly less maintenance than curating our
  own (B2), and it matches the ADR-0079 principle that schemas drive generic
  UI.
- No wire-format change and no migration: `action` is already a single
  string, and `data` stays a free-form dict merged from structured widgets
  and the Advanced JSON editor.
- react-colorful wins on size (2.8 KB, zero deps), accessibility, and
  maintenance. The literal-wheel aesthetic of C2 was judged not worth the
  extra packages; the picker style is an implementation detail behind the
  `color_rgb` selector mapping and can be swapped later without revisiting
  this ADR.

### Design sketch

Backend (`integrations_home_assistant`):

- `GET /api/alarm/home-assistant/services/` — new view following the
  `HomeAssistantNotifyServicesView` gateway pattern, backed by the existing
  `impl.list_services`. Response is slimmed server-side to keep payloads
  sane:

  ```json
  [
    {
      "domain": "light",
      "service": "turn_on",
      "name": "Turn on",
      "description": "...",
      "target": { "entity": [ { "domain": ["light"] } ] },
      "fields": {
        "rgb_color": { "selector": { "color_rgb": null }, "description": "..." },
        "brightness_pct": { "selector": { "number": { "min": 0, "max": 100 } } }
      }
    }
  ]
  ```

- No change to `action_schemas.py` validation or the action handler: `data`
  remains a free-form object; HA stays the authority on field semantics.

Frontend (`features/rules` + `features/homeAssistant`):

- New endpoint entry + service function + `useHomeAssistantServices` TanStack
  Query hook (long `staleTime`; the catalog changes only when HA integrations
  change).
- `ActionPicker` combobox (EntityPicker pattern): search across
  `domain.service` and friendly name; renders the identifier plus name;
  falls back to free-text entry (dot-validation preserved) when the catalog
  is empty.
- `ServiceDataFields`: given the picked service's `fields`, renders one
  widget per **known** selector — initial map deliberately small:
  `color_rgb` (react-colorful, writes `rgb_color: [r, g, b]`), `number`,
  `boolean`, `select`, `text`. Anything else is ignored by the structured
  layer and remains editable in the Advanced raw-JSON section. Widgets and
  the JSON editor read/write the same `data` object; keys the widgets don't
  own are passed through untouched.

## Acceptance Criteria

- [ ] **AC-1**: Given a rule with a `ha_call_service` action, when the action
  editor renders, then it shows a single **Action** field and the separate
  Domain/Service inputs no longer exist.
- [ ] **AC-2**: Given HA is configured and reachable, when the user opens the
  Action combobox and types a filter, then matching services from
  `GET /api/alarm/home-assistant/services/` are listed with their friendly
  names, and selecting one sets the action's `action` string to
  `domain.service`.
- [ ] **AC-3**: Given the services catalog is empty or the endpoint errors,
  when the user types a free-text value, then the value is accepted and the
  existing `domain.service` dot-validation still applies on save.
- [ ] **AC-4**: Given HA is configured, when
  `GET /api/alarm/home-assistant/services/` is called by an authenticated
  user, then it returns the domain/service catalog including per-field
  `selector` metadata, with auth requirements matching the existing HA
  entities/notify-services endpoints.
- [ ] **AC-5**: Given the user picks a service whose fields include a
  `color_rgb` selector (e.g. `light.turn_on`), when they use the color
  picker, then the action's `data.rgb_color` is set to an `[r, g, b]` integer
  array; number/boolean/select/text selectors likewise render structured
  widgets that write their keys into `data`.
- [ ] **AC-6**: Given an action whose `data` contains keys with unknown or
  unmapped selectors, when the user edits other fields and saves, then the
  unmapped keys survive unchanged and remain editable in the Advanced
  raw-JSON section.
- [ ] **AC-7**: Given existing saved rules with `ha_call_service` actions,
  when they are loaded, edited elsewhere, and re-saved, then their
  `action`/`target`/`data` payloads round-trip without loss (no migration
  performed or required).
- [ ] **AC-8**: Backend tests cover the new services view (configured,
  unconfigured, HA-error paths) and frontend tests cover the combobox
  (list/select/free-text fallback) and the selector-driven widgets including
  the `rgb_color` write path.

## Consequences

### Positive

- The rules builder finally matches the HA 2024.8+ "action" mental model —
  one identifier, searchable, with friendly names.
- Service data becomes self-describing: any HA service with selector
  metadata gets a structured form for free, now and for future HA releases.
- The JSON escape hatch is preserved, so nothing expressible today becomes
  inexpressible.
- Zero wire-format change; existing rules, the action handler, dispatch
  path, and backend validation are untouched.

### Negative

- New frontend subsystem (selector→widget mapper) to own and grow; initial
  selector coverage is deliberately narrow, so many services will still
  show mostly the JSON fallback at first.
- New runtime dependency (react-colorful, ~2.8 KB) — the first color-capable
  widget in the app.
- The full `/api/services` payload from HA can be large on
  integration-heavy installs; the endpoint slims it server-side and the
  frontend caches it, but it is still a heavier call than
  `notify-services`.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| HA selector metadata missing/odd for some integrations | Medium | Low | Unknown selectors fall back to the Advanced JSON editor; structured layer is additive only |
| Large catalog payload slows the editor | Low | Low | Server-side slimming; TanStack Query caching with long `staleTime`; fetch only when the action form is open |
| Structured widgets clobber hand-authored JSON keys | Low | Medium | Widgets own only their mapped keys; round-trip preservation is an explicit AC (AC-6) with tests |
| react-colorful abandoned later | Low | Low | Picker is isolated behind the `color_rgb` selector mapping; swappable without schema or data changes |

### Security Considerations

- The new endpoint is **read-only metadata** (service names + field schemas)
  and follows the same authentication as the existing HA entities endpoint.
  It does not execute anything.
- `ha_call_service` remains in `ADMIN_ONLY_ACTION_TYPES`; nothing in this
  change affects who can author or execute the action.

## Implementation Plan

- [ ] Phase 1 — Backend catalog: `services/` URL + view + gateway plumbing
  reusing `impl.list_services`; response slimming; view tests.
- [ ] Phase 2 — Action input: frontend endpoint/service/hook; `ActionPicker`
  combobox replacing the Domain/Service inputs in `HaCallServiceFields`;
  free-text fallback; ActionsEditor tests.
- [ ] Phase 3 — Service data: `ServiceDataFields` selector→widget mapper
  (`number`, `boolean`, `select`, `text`); Advanced JSON section; key
  round-trip tests.
- [ ] Phase 4 — Color: add react-colorful; `color_rgb` widget writing
  `rgb_color: [r, g, b]`; tests.

## Related ADRs

- [ADR-0079](0079-ui-config-with-encrypted-credentials.md) — established the
  schema-driven-UI principle this ADR extends to rule action forms.
- [ADR-0091](0091-rule-action-entry-delay.md) — precedent for evolving a rule
  action's fields and UI without a data migration.

## References

- [HA 2024.8 release notes — services renamed to actions](https://www.home-assistant.io/blog/2024/08/07/release-20248/)
- [HA REST API — `GET /api/services`](https://developers.home-assistant.io/docs/api/rest/)
  (note: the docs example predates the full-description response; HA core's
  `APIServicesView` returns `async_get_all_descriptions()` output including
  field selectors)
- [HA selectors reference](https://www.home-assistant.io/docs/blueprint/selectors/)
- [react-colorful](https://www.npmjs.com/package/react-colorful) ·
  [@uiw/react-color](https://github.com/uiwjs/react-color) (considered)
