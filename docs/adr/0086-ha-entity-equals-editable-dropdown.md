# ADR-0086: Domain-Aware Editable Dropdown for Home Assistant Entity `equals` Values

**Status:** Proposed
**Date:** 2026-04-20
**Author:** Leonardo Merza

## Context

### Background

In the visual rules builder, an `entity_state_ha` condition is an equality
check: "entity X equals value Y". When the user picks a Home Assistant entity
on the left, they must then type the exact canonical state string on the
right — `on` / `off` for binary sensors and switches, `locked` / `unlocked`
for locks, `open` / `closed` for covers, and so on. Today that right-hand
value is a plain free-text input, which means:

- Authors have to memorize the canonical state vocabulary of every HA domain.
- A typo (`"closed "`, `"Open"`, `"unlock"`) silently produces a rule that
  never fires — the worst possible failure mode for alarm automations, because
  it manifests as "nothing happened when I opened the door" at run time.
- Legitimate custom values (numeric `sensor` readings, ad-hoc HVAC modes from
  custom integrations) must still be supported, so a closed-set `<select>`
  would be a regression.

What we want is an *editable* combobox: the user sees a curated list of
suggested states appropriate to the selected entity's domain, but can still
type any custom value.

### Current State

- **Editor**: `frontend/src/features/rules/queryBuilder/valueEditors/EntityStateValueEditor.tsx`
  renders a `<EntityStatePicker>` (custom searchable popover for the
  entity_id) followed by a plain `<Input>` for the `equals` string
  (lines 137–144).
- **Value shape** (`frontend/src/types/rules.ts`):
  ```ts
  export interface EntityStateValue {
    entityId: string
    equals: string   // opaque string
  }
  ```
- **Entity metadata available at render time** (`frontend/src/types/rules.ts`):
  the `Entity` type already carries `domain: string`, populated by
  `backend/integrations_home_assistant/impl.py` from the `entity_id` prefix.
  The editor receives the full entity list in context, so the domain of the
  currently-selected entity is resolvable without any new API.
- **Backend semantics**: `backend/alarm/rules/conditions.py:289-297`
  evaluates the condition as a literal string equality:
  ```python
  if op == "entity_state":
      entity_id = node.get("entity_id")
      equals = node.get("equals")
      current = entity_state.get(entity_id)
      return current == equals
  ```
  There is no server-side schema for what `equals` can contain — it is an
  opaque string by design.
- **Existing UI primitive**: `frontend/src/components/ui/datalist-input.tsx`
  already wraps an `<Input>` with an HTML5 `<datalist>`. Its API is
  `{ listId, options: readonly string[], maxOptions?: number }` and it natively
  supports "pick from list OR type anything" with zero JS logic.

### Requirements

- When the user picks an entity, the `equals` input offers a dropdown of
  states canonical for that entity's domain.
- The user can still type any custom string; suggestions are hints, not
  constraints.
- Unknown domains (anything we don't have an entry for) degrade to today's
  behavior — plain text input.
- No change to persisted rule shape; rules authored before this change must
  load and evaluate identically.

### Constraints

- `alarm/rules/` cannot import from `integrations_*` or `transports_*`
  (enforced import boundary, CLAUDE.md). This ADR is frontend-only, so the
  boundary is not touched either way.
- No new runtime dependency: only `@radix-ui/react-slot` is installed; full
  Radix combobox primitives are not, and we don't want to pull one in for a
  single editor.
- The backend contract for `entity_state` is "opaque string equality" and
  must stay that way to preserve support for custom values.

## Options Considered

### Option 1: `DatalistInput` with a static domain→states map (chosen)

**Description:** Swap the plain `<Input>` in `EntityStateValueEditor` for the
existing `DatalistInput` component. Add a static module
`domainStateSuggestions.ts` that maps HA domains to their canonical state
lists. Derive the domain from the currently-selected entity and feed its
suggestions into the datalist.

**Pros:**
- Reuses a primitive already in the codebase; no new dependency.
- HTML5 `<datalist>` natively provides "pick OR type" with native keyboard
  and a11y behavior.
- Zero backend changes; `EntityStateValue` shape unchanged; no migration.
- Unknown domains fall through to `options: []`, which degrades to a plain
  input — existing authoring paths preserved.
- Suggestions are a client-side concern (UI guidance), which matches how they
  are actually used.

**Cons:**
- Suggestion map requires occasional maintenance if HA renames or adds
  domain states. Low churn in practice — HA canonical state vocabulary is
  stable across major versions.
- `<datalist>` styling is browser-controlled; we accept the default
  appearance rather than custom-styling the dropdown.

### Option 2: Full headless combobox (Radix/Downshift)

**Description:** Install a combobox library (e.g. `@radix-ui/react-popover`
+ custom listbox, or `downshift`) and build a custom styled combobox.

**Pros:**
- Fully custom styling that matches the rest of the rule builder.
- Fine-grained control over keyboard navigation and filtering.

**Cons:**
- New dependency for a single low-traffic editor.
- Non-trivial a11y surface to get right (we'd be re-implementing what
  `<datalist>` gives us for free).
- No user-visible benefit over Option 1.

### Option 3: Closed `<select>` with no free-text

**Description:** Replace the input with a plain `<select>` limited to the
known states for the entity's domain.

**Pros:**
- Simpler UI; no ambiguity about valid values.

**Cons:**
- Breaks legitimate custom values: sensor numeric states (`"27.5"`), custom
  integration states, HVAC modes that differ between integrations. This is a
  user-facing regression.
- Conflicts with the backend's opaque-string contract — effectively makes
  the frontend more restrictive than the data model.

### Option 4: Backend-driven suggestions from live HA state catalog

**Description:** Add an endpoint that asks Home Assistant for the currently
observed states of the selected entity (or domain), and feed those to the
combobox.

**Pros:**
- Suggestions reflect the actual environment, including custom states in use.

**Cons:**
- Round-trip latency on every entity pick.
- Failure modes: what do we show when HA is disconnected? (The rules builder
  must remain authorable offline.)
- Maintenance surface: new view, serializer, caching, tests — all to
  reproduce what a ~30-line static map covers.
- HA canonical states are stable; "live" adds volatility without value.

### Option 5: Server-side validation of `equals`

**Description:** Validate `equals` against the known domain states in
`RuleUpsertSerializer`.

**Pros:**
- Catches typos at save time, not at runtime.

**Cons:**
- Breaks custom values (numeric sensors, custom HVAC modes) — direct
  regression of today's behavior.
- Conflicts with the ADR'd "opaque string equality" semantics on the
  backend.

## Decision

**Chosen Option:** Option 1 — `DatalistInput` with a static domain→states map
maintained on the frontend.

**Rationale:**

- The problem is *guidance*, not validation. HTML5 `<datalist>` is the exact
  primitive for "suggested values with free-text fallback".
- `DatalistInput` already exists (`frontend/src/components/ui/datalist-input.tsx`)
  and is trivially drop-in where the plain `<Input>` is today. This is the
  smallest change that solves the pain point.
- Keeping suggestions on the frontend is consistent with the idea that the
  backend treats `equals` as opaque. We don't constrain the data model; we
  just help the UI.
- Unknown domains returning `[]` means the change is strictly additive — no
  path regresses.

### Sub-decisions

- **Where the map lives:**
  `frontend/src/features/rules/queryBuilder/valueEditors/domainStateSuggestions.ts`
  (colocated with other custom value editors). Exports
  `DOMAIN_STATE_SUGGESTIONS: Record<string, readonly string[]>` and a helper
  `getSuggestionsForDomain(domain: string | undefined): readonly string[]`
  that returns `[]` for unknown/undefined domains.
- **Initial domain → states map:**

  | Domain | Suggested states |
  |---|---|
  | `binary_sensor` | `on`, `off` |
  | `switch` | `on`, `off` |
  | `input_boolean` | `on`, `off` |
  | `light` | `on`, `off` |
  | `fan` | `on`, `off` |
  | `lock` | `locked`, `unlocked`, `locking`, `unlocking`, `jammed`, `unknown` |
  | `cover` | `open`, `closed`, `opening`, `closing`, `stopped` |
  | `climate` | `off`, `heat`, `cool`, `heat_cool`, `auto`, `dry`, `fan_only` |
  | `media_player` | `off`, `on`, `idle`, `playing`, `paused`, `standby`, `buffering` |
  | `person` | `home`, `not_home` |
  | `device_tracker` | `home`, `not_home` |
  | `sun` | `above_horizon`, `below_horizon` |
  | `alarm_control_panel` | `disarmed`, `armed_home`, `armed_away`, `armed_night`, `armed_vacation`, `armed_custom_bypass`, `pending`, `arming`, `triggered` |
  | `sensor` | *(none — values are arbitrary)* |

  Unlisted domains return `[]`. Adding a new domain is a one-line change.

- **Scope limited to the `equals` operator:** future operators
  (`not_equals`, `in`, `not_in`) can reuse the same map without schema
  changes, but are out of scope for this ADR.

- **No backend change:** `EntityStateValue`, `RuleUpsertSerializer`, and the
  `entity_state` condition handler are all untouched. Existing rules load and
  evaluate identically.

## Consequences

### Positive

- Faster, less error-prone rule authoring — the most common state strings are
  one keystroke away.
- Fewer silently-broken rules from state-string typos.
- Zero new dependencies; reuses an existing primitive.
- Zero backend risk — no migrations, no serializer changes, no new tests on
  the server.
- Authoring works offline / when HA is disconnected (suggestions are static).
- Sets a pattern we can extend to other "value-with-guidance" inputs later.

### Negative

- Suggestion map needs occasional updates as HA introduces or renames domain
  states. Low maintenance burden in practice.
- `<datalist>` rendering varies slightly by browser; we accept the native
  look rather than custom-styling it.
- Suggestions are UI-only guidance — a user determined to type a typo can
  still do so. This is intentional (to preserve custom values) and matches
  the backend's opaque-string contract.

### Neutral

- The map lives on the frontend, not in `SettingDefinition` / settings
  registry. This is correct: it's UI guidance, not configuration. ADR-0079's
  schema-driven settings model does not apply here.
- No change to the persisted `EntityStateValue` shape, so pre-existing rules
  are unaffected.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Map drifts from HA canonical states over time | Medium | Low | Unlisted states still work (free-text); fixing the map is a one-line PR. |
| User picks a sensor entity and is confused by the empty dropdown | Low | Low | Empty `options` causes `<datalist>` to not render a popup — visually identical to today's plain input, so no confusion vs. status quo. |
| Datalist styling mismatch vs. other form controls | Low | Low | Accept native rendering; revisit only if user feedback warrants a custom combobox later. |
| Domain lookup fails when entity is removed from HA but still referenced in a rule | Low | Low | `getSuggestionsForDomain(undefined)` returns `[]`; editor degrades to plain input; the existing "entity not found" affordance continues to apply. |

## Implementation Plan

- [ ] **Phase 1 — Suggestion map**
  - Add `frontend/src/features/rules/queryBuilder/valueEditors/domainStateSuggestions.ts`
    with `DOMAIN_STATE_SUGGESTIONS` and `getSuggestionsForDomain(domain)`.
  - Unit tests (`domainStateSuggestions.test.ts`): known domain returns
    expected list, unknown domain returns `[]`, `undefined` returns `[]`,
    helper returns the same reference on repeat calls (stable identity for
    React).

- [ ] **Phase 2 — Editor wiring**
  - In `EntityStateValueEditor.tsx`, resolve the selected entity's `domain`
    from the entity list in context.
  - Replace the plain `<Input>` for `equals` with `<DatalistInput>`,
    passing `options={getSuggestionsForDomain(selectedEntity?.domain)}` and
    a stable `listId` scoped to the editor instance.
  - Preserve all existing props: value, onChange, placeholder, disabled.

- [ ] **Phase 3 — Tests**
  - `EntityStateValueEditor.test.tsx`:
    - Picking a `binary_sensor` entity renders a datalist with `on`, `off`.
    - Picking a `lock` entity renders `locked` / `unlocked` / `jammed` / etc.
    - Picking a `sensor` entity renders no suggestions; plain typing works.
    - Typing a custom value (`"heat_cool"`, `"27.5"`) propagates via
      `onChange`.
    - Pre-existing rules with uncommon `equals` values load and render
      unchanged.
  - Frontend lint + typecheck: `npx eslint src/`, `npx tsc --noEmit`.
  - Full frontend suite: `npx vitest run`.

- [ ] **Phase 4 — Docs / status**
  - Update this ADR's status to **Implemented** once shipped.
  - No CLAUDE.md or README changes needed.

## Related ADRs

- [ADR-0033](./0033-react-query-builder-for-rules-ui.md) — React Query
  Builder UI; this change plugs into its `CustomValueEditor` dispatch.
- [ADR-0065](./0065-rule-builder-when-time-ranges.md) — precedent for
  non-trivial custom value editors in the rules builder.
- [ADR-0079](./0079-ui-config-with-encrypted-credentials.md) —
  schema-driven settings registry. Deliberately *not* used here: state
  suggestions are UI guidance, not configuration.

## References

- `frontend/src/features/rules/queryBuilder/valueEditors/EntityStateValueEditor.tsx`
  — current plain `<Input>` for `equals` (lines 137–144).
- `frontend/src/components/ui/datalist-input.tsx` — primitive to be reused.
- `frontend/src/features/rules/queryBuilder/RuleQueryBuilder.tsx` — field
  wiring and `CustomValueEditor` dispatch.
- `frontend/src/types/rules.ts` — `Entity.domain`, `EntityStateValue`.
- `backend/alarm/rules/conditions.py:289-297` — `entity_state` opaque string
  equality; proof no backend change is needed.
- `backend/integrations_home_assistant/impl.py` — domain derivation from
  entity_id prefix.
- Home Assistant canonical state constants:
  https://developers.home-assistant.io/docs/core/entity
