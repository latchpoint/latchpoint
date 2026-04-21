# ADR-0085: Rule Copy / Duplicate Action

**Status:** Proposed
**Date:** 2026-04-20
**Author:** Leonardo Merza

## Context

### Background

Users authoring alarm rules through the visual query builder frequently want to
create a new rule that is a small variation of an existing one (different
entity, different cooldown, same condition tree). Today the only paths are:

1. Manually re-authoring the rule from scratch.
2. Editing the original and then re-editing back — risky and error-prone.

A "copy" affordance on each rule would let the user clone the structure,
tweak the parts that differ, and save as a new rule.

### Current State

- `Rule` (`backend/alarm/models.py:322`) holds `name`, `kind`, `enabled`,
  `priority`, `stop_processing`, `stop_group`, `schema_version`,
  `definition` (JSON), `cooldown_seconds`, plus timestamps and `created_by`.
  `name` is **not** unique at the DB layer.
- `RuleEntityRef` (`backend/alarm/models.py:375`) links rules to entities;
  the upsert serializer populates these rows from the `entityIds` array in
  the upsert payload.
- The frontend `RulesPage` (`frontend/src/pages/RulesPage.tsx`) keeps a
  single `selectedRuleId` state. `null` means "new rule" and a numeric id
  means "edit existing". The `RuleBuilder` component renders the form and
  calls `useSaveRuleMutation`, which already distinguishes create vs update
  purely by whether `id == null`.
- The rules sidebar already renders per-rule buttons with name, kind,
  enabled flag, and priority.

### Requirements

- User can trigger "copy" from the rules list.
- A confirmation step prevents accidental copies.
- After confirming, the edit view opens pre-populated with cloned data so the
  user can adjust and save.
- Copy must not mutate or affect the original rule.
- Copying should carry over the full rule structure: definition (conditions
  and actions), priority, cooldown, stop flags, schema version, and entity
  references.

### Constraints

- `alarm/rules/` cannot import from `integrations_*` or `transports_*`
  (enforced import boundary, CLAUDE.md).
- Existing `RuleUpsertSerializer` is the authoritative create/update path;
  copy must not bypass its validation.
- `Rule.name` is non-unique, so uniqueness is a UI convention, not a DB
  guarantee — disambiguation must happen on the frontend.

## Options Considered

### Option 1: Frontend-only seed (chosen)

**Description:** Clone rule data on the client, open `RuleBuilder` with
`id = null` and the cloned fields as seed, let the user edit, and save via
the existing create path (`POST /api/rules/`).

**Pros:**
- Zero backend changes — reuses the already-authorized upsert serializer.
- No persistence side effect if the user cancels.
- `entityIds` flow through the existing upsert payload, so entity refs are
  duplicated implicitly on save.
- Identical validation path to any other new rule.

**Cons:**
- `RuleBuilder` needs to distinguish "editing rule X" from "seeded from rule
  X but saving as new" so it doesn't render the Delete button or send a
  stale id.
- If the user navigates away before saving, the copy is lost (acceptable —
  behaves like any unsaved form).

### Option 2: Backend copy endpoint

**Description:** Add `POST /api/rules/{id}/copy` that duplicates the `Rule`
and `RuleEntityRef` rows in a transaction, returns the new id, and the UI
navigates to `?edit=<newId>`.

**Pros:**
- Atomic, committed immediately; the copy is reloadable and deep-linkable.
- Entity refs duplicated inside a single transaction server-side.

**Cons:**
- New view, serializer, URL route, permission check, audit trail, and tests
  for a behavior the existing create path already supports.
- Creates a DB row even if the user cancels the edit — orphan
  "Rule (copy)" entries accumulate.
- Additional authorization surface area.

### Option 3: Hybrid (seed + validate endpoint)

**Description:** Frontend seeds the builder, but a new `POST /rules/validate`
endpoint pre-checks name and payload before the edit view opens.

**Pros:**
- Same UX as Option 1.
- Could surface "name already used" hints before the user edits.

**Cons:**
- Adds backend surface for minimal value — `Rule.name` isn't unique, so there
  is nothing to validate uniquely.
- Two-step feel for a conceptually one-click action.
- Most complex to implement and maintain.

## Decision

**Chosen Option:** Option 1 — Frontend-only seed.

**Rationale:**
- The existing `useSaveRuleMutation` already differentiates create vs update
  by `id == null`. Passing a cloned rule shape with `id = null` means the
  create path handles the copy without any special case on the backend.
- No DB row is created unless the user explicitly saves, which aligns with
  the user's mental model ("confirm to copy, then edit, then save") and
  avoids orphan rules.
- Backend validation (`RuleUpsertSerializer`) runs exactly as it does for any
  manually-authored rule — no duplicated validation logic.
- Option 2's only meaningful advantage (deep-linkable immediately) is not
  needed: the user wants to edit before committing.

### Sub-decisions

- **Button placement:** copy icon button on each row in the sidebar rules
  list (not in the builder header). Makes copy discoverable per-rule and
  reachable even while a different rule is being edited.
- **Name disambiguation:** append ` (copy)` to the name; on collision with an
  existing rule name in the loaded list, increment to ` (copy 2)`,
  ` (copy 3)`, etc. Convention familiar from macOS Finder / Google Drive.
- **Confirmation:** a `window.confirm("Copy rule \"<name>\"?")` gate — matches
  the existing delete confirmation pattern in `RulesPage.tsx:96`. Can be
  upgraded to a Radix dialog later if needed, but consistency with the
  codebase's current idiom is preferred.

## Consequences

### Positive

- Zero backend migration, zero new endpoint, zero new tests on the server.
- Copy is free to cancel; no cleanup needed.
- Feature ships as a focused frontend change touching `RulesPage`,
  `RuleBuilder`, and a small `cloneRule` helper.
- Sets a pattern for similar "duplicate" affordances elsewhere (notification
  providers, door codes) if later requested.

### Negative

- `RuleBuilder` must accept an initial seed that differs from "the rule
  being edited" — requires distinguishing `mode: 'edit' | 'create' | 'copy-seeded'`,
  or equivalently passing a nullable seed separate from the loaded rule.
- The copy lives only in the client until saved. If the user refreshes the
  page mid-edit, the cloned state is lost. Acceptable trade-off and
  consistent with all other "new rule" authoring.
- Name disambiguation runs only against the currently-loaded rules list;
  rules created by other sessions after page load could share a name. This
  is already possible today (no DB uniqueness) and is an acceptable UX
  quirk, not a correctness issue.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| User assumes copy is already saved and closes tab | Medium | Low | Label the builder clearly (e.g. "New rule (copied from X)") and keep the Save button prominent. |
| Deep-copy bugs: shared references in `definition` JSON mutate the original in React state | Low | Medium | Use `structuredClone(rule.definition)` (or equivalent) in the `cloneRule` helper; unit test that mutating a copy's definition does not change the source. |
| Sidebar row becomes crowded on small widths | Low | Low | Use an icon-only button with an `aria-label` and `title`; test at narrow widths. |
| Accidental click on copy icon | Low | Low | Confirmation dialog gates the action. |

## Implementation Plan

- [ ] **Phase 1 — Clone helper**
  - Add `frontend/src/features/rules/queryBuilder/cloneRule.ts` exporting
    `cloneRule(rule: Rule, existingNames: string[]): RuleSeed`.
  - Deep-clone `definition` with `structuredClone`.
  - Implement name disambiguation (`<name> (copy)`, `<name> (copy 2)`, …).
  - Strip server-only fields: `id`, `created_at`, `updated_at`, `created_by`.
  - Unit tests: increment logic, deep-clone independence, carry-over of
    priority / cooldown / stop_group / schema_version / entityIds.

- [ ] **Phase 2 — `RuleBuilder` seed support**
  - Extend props with an optional `seed?: RuleSeed` distinct from `rule`.
  - When `seed` is provided and `rule` is null, initialize form state from
    the seed; render as a new rule (no Delete button, header reads
    "New rule (copied from …)").
  - Ensure save payload sends `id: null` and includes `entityIds` from the
    seed.

- [ ] **Phase 3 — Sidebar copy button**
  - Add a `Copy` icon button (Lucide `Copy`) on each rule row in
    `RulesPage.tsx`. Place it inline, right-aligned, with `aria-label`
    `"Copy rule <name>"`.
  - Prevent row-click propagation so the sidebar's existing edit behavior
    is not triggered.
  - On click: `confirm("Copy rule \"<name>\"?")` → compute seed via
    `cloneRule(rule, rules.map(r => r.name))` → set new `seed` state,
    clear `selectedRuleId`, bump `builderNonce` so the builder remounts.

- [ ] **Phase 4 — Tests and docs**
  - `RulesPage.test.tsx`: copy button renders, confirmation gates the
    action, cancelling leaves state untouched, confirming opens builder
    seeded with cloned data and `id = null`.
  - `RuleBuilder.test.tsx`: seed prop initializes form; save path sends
    `id: null` with cloned fields.
  - `cloneRule.test.ts`: deep-copy and name disambiguation cases.
  - Update ADR status to Implemented once shipped.

## Related ADRs

- [ADR-0033](./0033-react-query-builder-for-rules-ui.md) — React Query Builder frontend for rules UI; the seed flow plugs into this component.
- [ADR-0076](./0076-per-rule-stop-processing-flag.md) — stop_processing flag; must be carried over on copy.
- [ADR-0084](./0084-user-named-stop-groups-for-rule-processing.md) — stop_group validation; copy inherits group verbatim, re-validated on save by `RuleUpsertSerializer`.

## References

- `backend/alarm/models.py:322` — `Rule` model.
- `backend/alarm/serializers/rules.py` — `RuleUpsertSerializer`.
- `frontend/src/pages/RulesPage.tsx` — current rules list and edit wiring.
- `frontend/src/hooks/useRulesQueries.ts:55` — save mutation (create/update branch on `id`).
- MDN `structuredClone` — https://developer.mozilla.org/en-US/docs/Web/API/structuredClone
