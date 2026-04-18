# ADR 0084: User-Named Stop Groups for Rule Processing

## Status
**Proposed** — Supersedes [ADR 0076](0076-per-rule-stop-processing-flag.md)

## Context

ADR 0076 introduced a per-rule `stop_processing` boolean that, when true, skips subsequent lower-priority rules **of the same kind**. Kind is auto-derived from the first action in the rule's `then` clause via `derive_kind_from_actions` (`backend/alarm/use_cases/rules.py:85-101`), which maps three action types explicitly and falls back to `"trigger"` for everything else.

In practice this has three problems:

### 1. Invisible scoping
The rule builder never displays the derived kind. Users toggle `stop_processing` without seeing which rules will actually be blocked. The only surface area for the concept is a HelpTip tooltip.

### 2. Semantic collision via fallback
Any rule whose first action is not `alarm_trigger`/`alarm_disarm`/`alarm_arm` — including notifications, HA service calls, Z-Wave writes, Zigbee writes — is classified as kind `trigger` by fallback. A notification-only rule is therefore grouped with a real alarm-trigger rule purely by accident of where it lands in a lookup table.

### 3. No user control over grouping
Even users who fully understand the mechanism cannot express intent like "these three door-entry rules form a group; within the group, stop_processing should cascade." Their only lever is to rearrange action ordering, which conflates action choice with stop-processing scope.

The kinds model itself (`trigger`, `disarm`, `arm`, `suppress`, `escalate`) remains valuable for categorization, audit logging, and UI filtering. This ADR does **not** remove kind. It decouples `stop_processing` from kind.

## Decision

Introduce a new optional `stop_group: CharField(max_length=64, blank=True, default="")` on the `Rule` model. Replace kind-based stop matching with exact string equality on `stop_group`. When `stop_group` is empty, `stop_processing` has no effect and the UI disables the toggle.

### 1. Model change

`backend/alarm/models.py`, on the `Rule` model:

```python
stop_group = models.CharField(
    max_length=64,
    blank=True,
    default="",
    help_text="Optional named group for stop_processing scoping. "
              "stop_processing only blocks lower-priority rules sharing this group.",
)
```

### 2. Dispatcher change

`backend/alarm/dispatcher/dispatcher.py` — replace the `stopped_kinds: set[str]` set with `stopped_groups: set[str]`. Ignore empty strings on both sides:

```python
stopped_groups: set[str] = set()
for rule in rules:
    if rule.stop_group and rule.stop_group in stopped_groups:
        logger.debug("Rule %s skipped: stop_group %s stopped", rule.id, rule.stop_group)
        self._stats.record_stopped()
        continue
    did_stop = self._evaluate_rule_with_lock(rule, entity_state_map, batch)
    if did_stop and rule.stop_group:
        stopped_groups.add(rule.stop_group)
```

`_evaluate_rule_with_lock` continues returning `bool`; it returns `True` only when `result.fired > 0 AND rule.stop_processing AND rule.stop_group`.

### 3. Rules engine change

`backend/alarm/rules_engine.py` — mirror the same `stopped_groups` set across both the due-runtimes loop and the main rules loop. Keep `RuleRunResult.skipped_stopped` semantics unchanged.

### 4. Simulation change

`simulate_rules()` annotations use `blocked_by_stop_group` (name of blocking group) alongside existing `blocked_by_rule_id`. The `blocked_by_stop_processing` boolean and summary `blocked` counter remain, so consumers upgrade by adding one field.

### 5. Validation

Add a model `clean()` check (and mirroring serializer validator) that rejects `stop_processing=True` with empty `stop_group`. Error message: `"stop_processing requires a non-empty stop_group."`

### 6. Serializer changes

Add `stop_group` to `RuleSerializer.Meta.fields` and `RuleUpsertSerializer.Meta.fields` in `backend/alarm/serializers/rules.py`. Cross-field validation enforces the stop_processing+stop_group invariant.

### 7. New API endpoint

`GET /api/alarm/rules/stop-groups/` returns the distinct set of non-empty `stop_group` values currently in use, for frontend autocomplete:

```json
{ "groups": ["door-entry-handling", "perimeter-alerts", "guest-mode-overrides"] }
```

Implementation: a single `Rule.objects.exclude(stop_group="").values_list("stop_group", flat=True).distinct()` call.

### 8. Frontend changes

**TypeScript types** (`frontend/src/types/rules.ts`):
- Add `stopGroup: string` to the `Rule` interface (default empty string)
- Add `blockedByStopGroup?: string` to `RuleSimulateEntry`

**Rule builder** (`frontend/src/features/rules/queryBuilder/RuleBuilder.tsx`):
- New text input (with autocomplete backed by the new endpoint) labeled "Stop group"
- Place the input directly above the existing "Stop processing" toggle
- Toggle is **disabled** when `stopGroup` is empty, with tooltip: "Set a stop group first to enable stop processing."
- Update the toggle label to interpolate the group: "Stop processing other rules in group **{stopGroup}**"
- Update the HelpTip: "When this rule fires, skip all lower-priority rules that share this stop group. Other rules are unaffected. Leave stop group empty to keep this rule's behavior isolated."

**Simulation results display**:
- Render the blocking group name next to blocked rules

**API hooks** (`frontend/src/hooks/useRulesQueries.ts`):
- Add `stopGroup` to create/update payload types
- New hook `useRuleStopGroups()` fetching the distinct-groups endpoint for autocomplete

### 9. No data migration

The app is pre-release. The new field is added with `default=""`. Existing `stop_processing=True` rules (if any exist in dev DBs) will simply have the flag silently ignored until a user assigns them a group — consistent with the new "opt-in" semantics.

## Alternatives Considered

### 1. Multi-tag groups (set intersection)
Each rule holds a list of group tags; stop matching uses set intersection. **Rejected**: adds UI complexity (tag editor vs single input), more confusing dispatch semantics ("which tag caused the block?"), and no strong use case — a rule that truly needs to be in two groups can usually be split into two rules.

### 2. Show derived kind in UI (keep current scoping)
Leave kind-based scoping intact, just display the derived kind live in the builder. **Rejected**: cheaper fix but leaves the fallback-to-trigger collision in place. Users still cannot express intentional groupings; they must arrange actions to manipulate an auto-derived string, which conflates two concerns.

### 3. Stop all lower-priority rules
Remove scoping entirely: `stop_processing=True` stops every subsequent rule regardless of category. **Rejected**: eliminates the ability to run kind-independent rules in the same evaluation (e.g., a logging rule should not be stopped by an unrelated trigger rule), and regresses the protections ADR 0076 added.

### 4. Keep kind-scoping and add an explicit per-rule `stop_group` as an optional override
A hybrid: use `stop_group` when set, fall back to kind when empty. **Rejected**: retains all of today's confusion for any rule that doesn't set a group. Pre-release status removes the compatibility argument for a hybrid.

## Consequences

### Positive
- **Explicit and visible**: the group is a field the user sets, displayed in the builder, used verbatim in labels and tooltips.
- **Separates concerns**: rule kind expresses "what does this rule do" (for audit/categorization); stop_group expresses "which rules does this one interact with" (for stop_processing scoping).
- **Eliminates the `trigger` fallback collision**: a notify-only rule no longer shares a stop group with an alarm-trigger rule unless the user explicitly names them the same.
- **Autocomplete reduces typos**: the distinct-groups endpoint surfaces existing names so users don't accidentally create `"door-entry"` and `"door_entry"` as separate groups.

### Negative
- **One more thing to configure**: users who want stop_processing must now also name a group. Mitigated by making the group field prominent in the UI and disabling stop_processing clearly when unset.
- **No group = no stopping**: opt-in semantics mean pre-release rules that had stop_processing checked will silently lose that effect until updated. Acceptable given pre-release status.
- **Typos are possible**: free-form strings admit typo-based non-matches. Mitigated by autocomplete; future enhancement could promote groups to first-class model objects if the string-based approach causes friction.

### Neutral
- `kind` remains in the model and is still auto-derived; it just no longer governs stop_processing.
- `RuleRunResult.skipped_stopped` semantics unchanged.

## Todos

### Docs
- [x] Write this ADR file
- [x] Mark ADR 0076 as `Superseded by 0084`
- [x] Add 0084 row to ADR 0000 index

### Backend
- [x] Add `stop_group` CharField to `Rule` in `backend/alarm/models.py`
- [x] Add model `clean()` enforcing stop_processing+stop_group invariant
- [x] Generate migration `backend/alarm/migrations/0017_rule_stop_group.py`
- [x] Replace `stopped_kinds` with `stopped_groups` in `backend/alarm/dispatcher/dispatcher.py`
- [x] Replace `stopped_kinds` with `stopped_groups` in `backend/alarm/rules_engine.py` (both `run_rules` and `simulate_rules`)
- [x] Update simulation annotations: `blocked_by_stop_group` in place of implicit kind
- [x] Update `RuleSerializer` and `RuleUpsertSerializer` in `backend/alarm/serializers/rules.py`; add cross-field validator
- [x] New endpoint `GET /api/alarm/rules/stop-groups/` in `backend/alarm/views/rules.py`
- [x] Update/replace tests in `backend/alarm/tests/test_dispatcher_stop_processing.py` (remove same-kind assertions; add same-group assertions)

### Frontend
- [x] Add `stopGroup: string` to `Rule` in `frontend/src/types/rules.ts`; update related types
- [x] Add Stop group input (with autocomplete) in `frontend/src/features/rules/queryBuilder/RuleBuilder.tsx`
- [x] Disable stop_processing toggle when stopGroup is empty; update label+tooltip to interpolate group
- [x] Add `useRuleStopGroups()` hook in `frontend/src/hooks/useRulesQueries.ts`
- [x] Update simulation results display to show blocking group name
- [x] Update the run-result notice if `skippedStopped` output needs label refinement

### Tests
- [x] `test_stop_processing_blocks_same_group` (higher-priority rule with group `G`, stop_processing=True blocks lower-priority rule with group `G`)
- [x] `test_stop_processing_does_not_block_different_group` (group `G` does not stop group `H`)
- [x] `test_stop_processing_no_group_is_no_op` (stop_processing=True, stop_group="" → no stopping)
- [x] `test_validation_rejects_stop_processing_without_group`
- [x] `test_distinct_stop_groups_endpoint`
- [x] Frontend RuleBuilder test: toggle disabled when group empty, enabled when set
- [x] Verify existing regression: `test_multiple_matching_rules_all_fire` still passes

## References
- [ADR 0076](0076-per-rule-stop-processing-flag.md) — superseded by this ADR
- [ADR 0006](0006-rules-engine-internal-modules.md) — original "stop-after-fire" todo
- Rule model: `backend/alarm/models.py`
- Dispatcher: `backend/alarm/dispatcher/dispatcher.py:260-268`
- Rules engine: `backend/alarm/rules_engine.py`
- Use case: `backend/alarm/use_cases/rules.py:85-101` (kind derivation — unchanged, retained for categorization)
- Rule builder: `frontend/src/features/rules/queryBuilder/RuleBuilder.tsx:260-287`
