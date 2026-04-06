# ADR 0076: Per-Rule `stop_processing` Flag

## Status
**Implemented**

## Context

Latchpoint's rules engine evaluates all enabled rules ordered by `-priority, id`. When multiple rules match the same conditions, **all of them fire**. Priority only controls execution order, not whether a rule executes. This is validated by `test_multiple_matching_rules_all_fire` in `backend/alarm/tests/test_rules_priority.py`.

This "fire all" behavior is correct as the default, but it creates problems for common alarm system patterns:

### 1. Override / fallback patterns
An operator may want a high-priority rule that, when it fires, **supersedes** lower-priority rules. For example:
- A high-priority "suppress" rule that recognizes a known-safe condition (e.g., "pet detected by Frigate with confidence > 80%") should prevent a lower-priority "trigger" rule from also firing on the same motion event.
- A high-priority "disarm" rule (e.g., "authorized person detected at front door") should prevent a lower-priority "disarm" rule with different actions from also executing.

### 2. Conflicting actions
Without a way to stop evaluation, both a "suppress" rule and a "trigger" rule can fire in the same evaluation cycle. Their actions may conflict: one suppresses, the other triggers. The outcome depends on action execution order within the cycle, which is fragile and confusing.

### 3. ADR 0006 todo
ADR 0006 (Rules Engine Internal Decomposition) includes an explicit open todo:
> Add "stop-after-fire" and conflict resolution policy as explicit engine configuration.

### 4. Two execution paths
The rules engine has two paths where stop behavior must take effect:

- **Scheduled path** (`run_rules()` in `backend/alarm/rules_engine.py`): Iterates all enabled rules in a single loop ordered by `-priority, id`.
- **Real-time dispatcher path** (`_dispatch_batch()` in `backend/alarm/dispatcher/dispatcher.py`): For an entity state change, resolves impacted rules and evaluates each one individually via `_evaluate_rule_with_lock()`, which calls `run_rules()` with a single-rule repository.

---

## Decision

Add a **per-rule boolean field** `stop_processing` (default `False`) to the `Rule` model. When a rule with `stop_processing=True` fires (condition matched and actions executed), remaining lower-priority rules **of the same kind** in the same evaluation context are skipped.

### 1. Model change

```python
# backend/alarm/models.py — Rule model, after the priority field
stop_processing = models.BooleanField(default=False)
```

Default `False` ensures full backward compatibility: all existing rules continue to fire as before.

### 2. Same-kind scoping

`stop_processing` only blocks subsequent rules **of the same `kind`**. A trigger rule with `stop_processing=True` blocks other trigger rules but does not block disarm, arm, suppress, or escalate rules.

The five rule kinds are defined in `RuleKind` (`backend/alarm/models.py`):

```python
class RuleKind(models.TextChoices):
    TRIGGER = "trigger", "Trigger"
    DISARM = "disarm", "Disarm"
    ARM = "arm", "Arm"
    SUPPRESS = "suppress", "Suppress"
    ESCALATE = "escalate", "Escalate"
```

**Rationale**: These kinds represent independent decision axes. The "should we trigger?" decision is separate from "should we disarm?". A global stop would mean a high-priority trigger rule could accidentally block all disarm rules, leaving the alarm stuck with no automated off-ramp. Same-kind scoping limits the blast radius of any misconfiguration.

### 3. Scheduled path (`run_rules()`)

In `backend/alarm/rules_engine.py`, track `stopped_kinds: set[str]` across both the due-runtimes loop and the main rules loop:

```python
stopped_kinds: set[str] = set()
stopped = 0

# In each loop, before evaluating a rule:
if rule.kind in stopped_kinds:
    stopped += 1
    continue

# After a rule fires successfully:
if rule.stop_processing:
    stopped_kinds.add(rule.kind)
```

Both loops share the same `stopped_kinds` set since they run in the same `run_rules()` invocation.

### 4. `RuleRunResult` extension

```python
@dataclass(frozen=True)
class RuleRunResult:
    evaluated: int
    fired: int
    scheduled: int
    skipped_cooldown: int
    skipped_stopped: int   # NEW
    errors: int
```

Stopped rules are not counted in `evaluated` since their conditions were never checked. The `as_dict()` method includes `"skipped_stopped"`.

### 5. Dispatcher path

**`_evaluate_rule_with_lock`** (`backend/alarm/dispatcher/dispatcher.py`): Change return type from `None` to `bool`. Return `True` when the rule fired AND has `stop_processing=True`, `False` otherwise.

**`_dispatch_batch`**: Track `stopped_kinds: set[str]` across the rule loop:

```python
stopped_kinds: set[str] = set()
for rule in rules:
    if rule.kind in stopped_kinds:
        logger.debug("Rule %s skipped: kind %s stopped", rule.id, rule.kind)
        continue
    did_stop = self._evaluate_rule_with_lock(rule, entity_state_map, batch)
    if did_stop:
        stopped_kinds.add(rule.kind)
```

In the dispatcher path, this naturally scopes to rules impacted by the same entity-change batch.

### 6. Simulation (`simulate_rules()`)

In `backend/alarm/rules_engine.py`, the simulation tracks `stopped_kinds` during iteration. Rules blocked by a prior stop are annotated in the output:

```python
{
    "id": rule.id,
    "name": rule.name,
    "kind": rule.kind,
    "priority": rule.priority,
    "matched": False,
    "blocked_by_stop_processing": True,
    "blocked_by_rule_id": <id of rule that triggered the stop>,
}
```

A new summary counter `"blocked"` tracks how many rules were skipped. Blocked rules appear in the `non_matching_rules` list with the blocking annotation for clear debugging.

### 7. Serializer changes

Add `"stop_processing"` to both `RuleSerializer.Meta.fields` and `RuleUpsertSerializer.Meta.fields` in `backend/alarm/serializers/rules.py`.

### 8. Frontend changes

**TypeScript types** (`frontend/src/types/rules.ts`):
- Add `stopProcessing: boolean` to the `Rule` interface
- Add `skippedStopped: number` to the `RuleRunResult` interface
- Add optional `blockedByStopProcessing?: boolean` and `blockedByRuleId?: number` to `RuleSimulateEntry`
- Add `blocked: number` to the simulation summary type

**Rule builder** (`frontend/src/features/rules/queryBuilder/RuleBuilder.tsx`):
- Add a switch/checkbox near the priority field: "Stop processing lower-priority rules of the same kind when this rule fires"
- Include `stopProcessing` in the save payload

**Run result notice** (`frontend/src/lib/notices.ts`):
- Include `skippedStopped` in the formatted notice output

**Simulation results display**:
- Show a blocked indicator when a rule has `blockedByStopProcessing: true`

**API hooks** (`frontend/src/hooks/useRulesQueries.ts`):
- Add `stopProcessing` to create/update payload types

### 9. Audit log trace

When a rule with `stop_processing=True` fires, include `"stop_processing": true` in the trace dict passed to `log_rule_action`. This provides a clear audit trail for why subsequent rules were skipped.

### 10. Migration

A single Django migration (`backend/alarm/migrations/0016_rule_stop_processing.py`) adding the `stop_processing` BooleanField with `default=False`. This is non-destructive and backward-compatible.

---

## Alternatives Considered

### 1. Global engine configuration (ADR 0006 original suggestion)
A single engine-wide "stop-after-fire" policy. **Rejected**: Too coarse. Operators need some rules to be "final" and others to always fire (e.g., logging/notification rules should fire alongside action rules). A global flag would force all rules into one behavior.

### 2. Per-entity scoping
`stop_processing` only blocks rules that reference overlapping entities. **Rejected**: Complex to implement (requires entity-set intersection checks), hard to reason about (which entities count?), and ambiguous when rules partially overlap in entity references. The kind-based scope is unambiguous and efficient.

### 3. Explicit conflict resolution DSL
Allow rules to declare "conflicts_with" or "overrides" relationships by name or ID. **Rejected**: Over-engineered for the current scale. Per-rule `stop_processing` with priority ordering achieves the same result with a simpler mental model.

### 4. Priority-group exclusive mode
Rules with the same priority form a group; only one in the group fires. **Rejected**: Priority values are arbitrary integers and grouping semantics would be confusing. Operators would need to carefully coordinate priority values across rules.

---

## Consequences

### Positive
- **Enables override patterns**: High-priority suppress rules can prevent false alarms without conflicting with lower-priority trigger rules.
- **Fully backward compatible**: `stop_processing` defaults to `False`, so all existing rules and tests continue to work unchanged.
- **Simple mental model**: "Rules fire in priority order within their kind. A rule with 'stop processing' is the final word for its kind in that evaluation."
- **Same-kind scoping prevents dangerous cross-kind interference**: A trigger rule cannot block disarm rules, preventing stuck-alarm scenarios.
- **Closes ADR 0006 todo**: The "stop-after-fire and conflict resolution policy" requirement is fulfilled.

### Negative
- **Ordering footgun**: Behavior depends on relative priority values. If two rules both have `stop_processing=True` and the same priority, the one with the lower `id` (creation order) wins. Mitigation: frontend warning when saving a rule with `stop_processing=True` if another rule of the same kind also has `stop_processing=True` at the same priority.
- **Debugging complexity**: When rules are skipped, it may be non-obvious why. Mitigation: simulation view shows `blocked_by_rule_id` and audit log traces include the stop flag.

### Neutral
- `RuleRunResult` gains one new field; all consumers must be updated (mechanical change).
- The dispatcher's `_evaluate_rule_with_lock` return type changes from `None` to `bool` (localized to dispatcher module).

---

## Todos

### Backend: Model + Migration
- [ ] Add `stop_processing = models.BooleanField(default=False)` to `Rule` in `backend/alarm/models.py`
- [ ] Generate migration: `backend/alarm/migrations/0016_rule_stop_processing.py`

### Backend: `RuleRunResult`
- [ ] Add `skipped_stopped: int` to `RuleRunResult` in `backend/alarm/rules_engine.py`
- [ ] Update `as_dict()` to include `"skipped_stopped"`

### Backend: `run_rules()` scheduled path
- [ ] Add `stopped_kinds: set[str]` and `stopped: int` tracking in `backend/alarm/rules_engine.py`
- [ ] In due-runtimes loop: skip if `rule.kind in stopped_kinds`; after firing, add kind if `stop_processing`
- [ ] In main rules loop: skip if `rule.kind in stopped_kinds`; after firing, add kind if `stop_processing`
- [ ] Return `skipped_stopped=stopped` in `RuleRunResult`

### Backend: Dispatcher
- [ ] Change `_evaluate_rule_with_lock` return type to `bool` in `backend/alarm/dispatcher/dispatcher.py`
- [ ] Add `stopped_kinds` tracking in `_dispatch_batch`
- [ ] Update `DispatcherStats` in `backend/alarm/dispatcher/stats.py` with stopped counter

### Backend: `simulate_rules()`
- [ ] Add `stopped_kinds` tracking in `backend/alarm/rules_engine.py`
- [ ] Annotate blocked rules with `blocked_by_stop_processing` and `blocked_by_rule_id`
- [ ] Add `"blocked"` to simulation summary

### Backend: Serializers
- [ ] Add `"stop_processing"` to `RuleSerializer.Meta.fields` in `backend/alarm/serializers/rules.py`
- [ ] Add `"stop_processing"` to `RuleUpsertSerializer.Meta.fields` in `backend/alarm/serializers/rules.py`

### Frontend: Types
- [ ] Add `stopProcessing: boolean` to `Rule` in `frontend/src/types/rules.ts`
- [ ] Add `skippedStopped: number` to `RuleRunResult`
- [ ] Add `blockedByStopProcessing?` and `blockedByRuleId?` to `RuleSimulateEntry`
- [ ] Add `blocked: number` to simulation summary type

### Frontend: UI
- [ ] Add `stopProcessing` toggle in `frontend/src/features/rules/queryBuilder/RuleBuilder.tsx`
- [ ] Update run result notice in `frontend/src/lib/notices.ts`
- [ ] Add blocked indicator in simulation results display
- [ ] Add `stopProcessing` to API payload in `frontend/src/hooks/useRulesQueries.ts`

### Tests
- [ ] `test_stop_processing_skips_lower_priority_same_kind` — higher-priority rule stops, lower-priority same-kind rule skipped
- [ ] `test_stop_processing_does_not_block_different_kind` — trigger stop does not block disarm
- [ ] `test_stop_processing_false_does_not_skip` — default behavior preserved
- [ ] `test_stop_processing_non_matching_rule_does_not_stop` — non-matching stop rule does not block
- [ ] `test_simulate_shows_blocked_rules` — simulation annotates blocked rules
- [ ] Verify `test_multiple_matching_rules_all_fire` still passes (regression guard)
- [ ] Backend tests in `backend/alarm/tests/test_rules_priority.py`

### Documentation
- [ ] Update ADR 0006 todos: mark "stop-after-fire" as done (ADR 0076)

---

## References

- [ADR 0006: Rules Engine Internal Decomposition](0006-rules-engine-internal-modules.md) — todo fulfilled by this ADR
- Scheduled path: `backend/alarm/rules_engine.py` (`run_rules`, `simulate_rules`)
- Dispatcher path: `backend/alarm/dispatcher/dispatcher.py` (`_dispatch_batch`, `_evaluate_rule_with_lock`)
- Rule model: `backend/alarm/models.py` (`Rule`, `RuleKind`)
- Serializers: `backend/alarm/serializers/rules.py`
- Frontend types: `frontend/src/types/rules.ts`
- Rule builder: `frontend/src/features/rules/queryBuilder/RuleBuilder.tsx`
- Existing priority tests: `backend/alarm/tests/test_rules_priority.py`
