# ADR-0108: Per-Condition "Changed Since Alarm Transition" Flag for `entity_state` Rule Conditions

**Status:** Proposed
**Date:** 2026-09-04
**Author:** Leonardo Merza

## Context

### Background

On 2026-09-03 the prod instance armed itself (the presence-driven `away` rule
fired when both occupants left) while the **side fence door was already open**.
The moment the 60 s exit delay ended, the `trigger` rule fired, put the alarm
into PENDING for its 60 s entry delay (ADR-0091), and then TRIGGERED the siren.
Nobody had touched the fence door. The same thing happened on 2026-09-01.

Ground truth from `alarm_alarmevent` and `alarm_ruleactionlog` (local time,
America/New_York):

| Time | Event | Detail |
|------|-------|--------|
| 2026-09-03 11:14:15.424 | rule 4 `away` fired | `alarm_arm armed_away` → state `arming` (60 s exit delay) |
| 2026-09-03 11:15:16.177 | `arming → armed_away` | exit delay expired |
| 2026-09-03 11:15:16.385 | rule 3 `trigger` fired | `alarm_trigger` deferred 60 s → `pending` (**+0.21 s after arm**) |
| 2026-09-03 11:16:16.702 | `pending → triggered` | siren |
| 2026-09-03 11:21:25.506 | `triggered → disarmed` | keypad code |
| 2026-09-01 11:16:46.288 | `arming → armed_away` | |
| 2026-09-01 11:16:46.497 | `armed_away → pending` | **+0.21 s after arm**, then triggered at 11:17:46 |

Every other PENDING since June happened minutes or hours after arming, i.e.
was a real door event. The two sub-second cases are this defect.

### Current State

**Why the rule fires at arm time.** The rules engine is *level-triggered with
edge detection on the whole WHEN expression*: `run_rules()`
(`backend/alarm/rules_engine.py`) fires a rule when its WHEN goes from not
matched to matched (`RuleRuntimeState.last_when_matched`). It has no notion
of *which* clause caused the edge.

Alarm transitions are fed into the same dispatcher as a synthetic entity
`__system.alarm_state` (`backend/alarm/ws_signals.py` →
`notify_entities_changed`), so every rule containing `alarm_state_in` is
re-evaluated on every transition. The prod trigger rule (id 3) is:

```json
{"op": "all", "children": [
  {"op": "alarm_state_in", "states": ["armed_home", "armed_away", "armed_night", "armed_vacation"]},
  {"op": "any", "children": [
    {"op": "entity_state", "entity_id": "binary_sensor.back_door_window_door_is_open",   "equals": "on"},
    {"op": "entity_state", "entity_id": "binary_sensor.front_door_window_door_is_open",  "equals": "on"},
    {"op": "entity_state", "entity_id": "binary_sensor.garage_door_window_door_is_open", "equals": "on"},
    {"op": "entity_state", "entity_id": "binary_sensor.corner_fence_door_sensor_door",   "equals": "on"},
    {"op": "entity_state", "entity_id": "binary_sensor.side_fence_door_sensor_door",     "equals": "on"}
  ]}
]}
```

With the fence door open, `any(...)` is already true. Arming flips
`alarm_state_in` to true, the whole WHEN edges false→true, and the rule fires.
The "pet sitter mode" rule (id 2) has the same shape and the same defect.

**Data that already exists:**

- `Entity.last_changed` (`backend/alarm/models.py:295`, indexed). Stamped from
  Home Assistant's own `last_changed` by the WebSocket state stream
  (`backend/integrations_home_assistant/state_stream.py:278`), with local
  `now` by the 300 s reconciliation poll (`backend/alarm/tasks.py:231`, only
  when the state actually differs, ADR-0102), and with `now` by the Z-Wave JS
  and Zigbee2MQTT sync paths. HA's `last_changed` only moves when the *state
  value* changes (attribute-only updates move `last_updated`), so it is a
  faithful "last state change" timestamp for HA entities.
- `AlarmStateSnapshot.entered_at` (`backend/alarm/models.py:80`), set on every
  `transition()` in `backend/alarm/state_machine/snapshot_store.py`.

**Evaluation plumbing:**

- `entity_state` node shape today: `{op, entity_id, equals, source?}`.
  Validated by `validate_when_node`, evaluated by
  `eval_condition_with_context`, explained by
  `eval_condition_explain_with_context` (all in
  `backend/alarm/rules/conditions.py`).
- `RuleEngineRepositories` (`backend/alarm/rules/repositories.py`) is a frozen
  dataclass of seven callables. The dispatcher builds a per-batch scoped
  `entity_state_map` (`dict[entity_id, last_state]`) from one `values_list`
  query (ADR-0061) and reads `alarm_state` lazily through
  `repos.get_alarm_state()` so a rule that arms/disarms earlier in the same
  run is visible to later rules.
- Frontend: React Query Builder. `EntityStateValueEditor.tsx` renders entity
  picker + `equals`; `converters.ts` round-trips `EntityStateNode`;
  `types/ruleDefinition.ts` holds the type + guard.

**What is not in play:** the legacy `Sensor.is_entry_point` path
(`sensor_triggered()` in `transitions.py`) is unused in prod (`alarm_sensor`
is empty). The broader Alarmo-style sensor model / ready-to-arm design lives
in `docs/planning/enhanced-sensors-ready-to-arm.md` (Draft) and is
deliberately **not** pulled into this ADR.

### Requirements

- **R1** Per-condition opt-in: a sensor that was already in the matching state
  when the alarm entered its current state must not satisfy the condition.
- **R2** The next genuine change *into* the matching state after the
  transition must satisfy it (fence door closed, then opened again → trigger).
- **R3** While one sensor is being ignored, every other sensor in the same
  `any(...)` group must remain fully effective.
- **R4** Level conditions in the same rule (`input_boolean.guest_mode == on`,
  `input_boolean.pet_sitter_mode == on`) must be unaffected unless opted in.
- **R5** The rules test page / explain trace must show *why* a condition was
  ignored.
- **R6** Rules without the flag behave exactly as today.
- **R7** No schema migration.

### Constraints

- `alarm/rules/` must not import `integrations_*` / `transports_*` (enforced by
  `test_import_boundaries_rules_use_cases.py`). All new reads go through
  `RuleEngineRepositories`.
- `RuleEngineRepositories` is constructed in `repositories.py`,
  `dispatcher.py` and `rules_engine.py::simulate_rules` plus tests. New fields
  need defaults so those call sites keep compiling.
- Dispatcher hot path (ADR-0061): no additional query per rule; `last_changed`
  must ride along in the existing scoped `values_list`.
- HA entity timestamps come from HA's clock. In the reference deployment HA
  runs on the same host as Latchpoint (`docker-compose.home.yml`), so skew is
  zero; other deployments rely on NTP.

## Options Considered

### Option 1: Per-condition `changed_since_alarm_transition` flag on `entity_state` (chosen)

**Description:** Add an optional boolean to the `entity_state` node. When true,
the condition is satisfied only if `last_state == equals` **and**
`Entity.last_changed > AlarmStateSnapshot.entered_at`. One checkbox in the
rule builder per entity condition.

**Pros:**
- Per-condition, so level conditions in the same rule stay level (R4). The
  prod `pet sitter mode` rule mixes `input_boolean.pet_sitter_mode == on`
  (level) with five door conditions (edge) — a per-rule flag could not
  express that.
- No migration: both timestamps already exist (R7).
- Solves the multi-door case correctly (R3): the ignored door evaluates
  false, so `any(...)` is false, so a second door opening produces a fresh
  false→true edge.
- Side effect: a door left open through a full bell cycle no longer re-fires
  the trigger rule on every return-to-armed, which matches commercial panel
  behaviour (new violation required).
- Explain trace can say "ignored: changed before alarm transition" (R5).
- Small, contained PR: `conditions.py`, `repositories.py`, dispatcher scoped
  map, one value editor, converters + types.

**Cons:**
- Timestamp comparison across two writers. HA entity `last_changed` is HA's
  clock; `entered_at` is ours. Skew of the wrong sign would make a door
  opened just *after* arming look like *before* and be ignored. Same host in
  prod → zero skew; NTP elsewhere.
- A door opened during the exit delay and left open is also ignored once
  `armed_*` is entered (its `last_changed` precedes the `arming → armed`
  transition). Commercial panels call this an "exit error" and alarm. Prod
  auto-arms only after everyone has left, so nobody is walking through a door
  during the exit delay; accepted, see Risks.
- `unavailable → on` blips (HA restart, Z-Wave dropout) bump `last_changed`
  and would un-ignore an open door. See Risks.
- The operator has to tick the box on each door condition (five in each of
  two prod rules).

### Option 2: Arm-time auto-bypass set on the snapshot

**Description:** On arm, walk enabled rules that contain an `alarm_trigger`
action, find `entity_state` conditions currently satisfied, and persist them
in a new `AlarmStateSnapshot.bypassed_entity_ids` JSON field. The evaluator
treats bypassed entities as non-matching until their state changes, at which
point they leave the set. UI/keypad/notifications can announce "armed with
side fence door bypassed"; could publish HA `armed_custom_bypass`.

**Pros:**
- Visible to the user; matches the industry "force arm with auto-bypass"
  model and the direction of `docs/planning/enhanced-sensors-ready-to-arm.md`.
- Nothing to remember per condition.

**Cons:**
- Migration plus new state to keep coherent across
  arming/pending/triggered/return-to-armed/disarm and across settings
  profiles.
- The engine is generic: it does not know that `on` means "faulted". "Faulted"
  has to be inferred from rule definitions, which is exactly the coupling
  ADR-0004 removed when it deleted zones.
- A level condition on a `binary_sensor`/`input_boolean` in a trigger rule
  would be wrongly bypassed unless it opts out — which reintroduces a
  per-condition flag anyway.
- Larger surface: state machine, dispatcher repos, WebSocket payload,
  dashboard, MQTT alarm entity.

**Why not:** Right feature for the ready-to-arm epic, wrong size for this
defect. Option 1 is a prerequisite for it (the per-condition opt-out), not a
competitor.

### Option 3: Per-rule "only fire on sensor change" flag

**Description:** `Rule.fire_only_on_entity_change`. In `run_rules`, if the
batch's `triggering_entity_ids` does not intersect the rule's `entity_state`
entity ids (i.e. the edge came from `__system.alarm_state`), update
`last_when_matched` but do not fire.

**Pros:**
- No timestamps, no clock domains. One checkbox per rule.

**Cons:**
- **Security hole.** With the fence door open, `any(...)` is already true and
  `last_when_matched` is recorded true (suppressed). A *second* door opening
  produces no rising edge, so the rule never fires while the first door stays
  open. Every other door is unprotected. Fails R3.
- Timer (`for`), manual "run rules", and the 5 s `process_due_rule_runtimes`
  task pass no batch → would never fire such rules.
- Cannot mix level and edge conditions in one rule. Fails R4.

**Why not:** Rejected on R3 alone.

### Option 4: Not-ready-to-arm pre-check

**Description:** In `arm()`, evaluate trigger rules' entity conditions; if any
is satisfied, refuse the arm with the list of open sensors unless
`force=true`, or proceed and notify.

**Pros:**
- The user learns the fence door is open before leaving. Standard "Not
  Ready" panel behaviour.

**Cons:**
- Does not fix rule-driven auto-arm. The prod `away` rule arms when both
  presence booleans go off; a refused auto-arm leaves the house **disarmed
  silently**, which is strictly worse than today.
- Warn-and-proceed still triggers the alarm today unless combined with
  Option 1 or 2.
- Needs a force path through every arm entry point (UI, MQTT/HA card, Ring
  keypad, rules).

**Why not:** Complementary, not a fix. Belongs to the ready-to-arm planning
doc, layered on top of Option 1.

### Sub-decision: which timestamp to compare against

| Candidate | Pros | Cons |
|-----------|------|------|
| **`AlarmStateSnapshot.entered_at` of the current state** (chosen) | Exists; no migration; one read that mirrors `get_alarm_state()`; "changed since the alarm entered its current state" is a clean, state-agnostic sentence that also makes sense for `disarmed`/`triggered` rules | Resets on *every* transition, so a door opened during exit delay or during the siren is ignored once the alarm returns to `armed_*` |
| New `AlarmStateSnapshot.armed_since` (set on `disarmed → arming/armed_*`, cleared on disarm, kept across pending/triggered) | Doors opened during exit delay still count ("exit error"); doors opened during the siren re-trigger on return to armed | Migration + prod migrate; semantics undefined for non-armed rules; re-trigger loop on a still-open door returns |

`entered_at` chosen. `armed_since` can be added later as a second reference
without changing the flag's shape.

## Decision

**Chosen Option:** Option 1, comparing against `AlarmStateSnapshot.entered_at`.

**AST shape** (new key is optional; absent or `false` = today's semantics):

```json
{
  "op": "entity_state",
  "entity_id": "binary_sensor.side_fence_door_sensor_door",
  "equals": "on",
  "source": "home_assistant",
  "changed_since_alarm_transition": true
}
```

**Evaluation** (`eval_condition_with_context`, `entity_state` branch):

```
matched = (last_state == equals)
if changed_since_alarm_transition:
    last_changed = entity_last_changed.get(entity_id)      # dict built once per run
    entered_at   = repos.get_alarm_state_entered_at()       # lazy, like get_alarm_state()
    matched = matched and last_changed is not None
                      and entered_at is not None
                      and last_changed > entered_at
```

Missing `last_changed` or `entered_at` evaluates **false** (never fires on
unknown data) and is reported in the trace. Strict `>`: a change stamped at
exactly the transition instant is "before".

**Repositories:** two new callables on `RuleEngineRepositories`, both with
defaults so existing constructors are untouched:

- `entity_last_changed_map: Callable[[], dict[str, datetime | None]]`
  (default `lambda: {}`). Default impl reads `Entity.last_changed`; the
  dispatcher extends its scoped query to
  `values_list("entity_id", "last_state", "last_changed")` and splits it into
  the two maps — no extra query on the hot path.
- `get_alarm_state_entered_at: Callable[[], datetime | None]`
  (default `lambda: None`). Default impl reads the same snapshot row
  `get_alarm_state()` reads.

`run_rules` and `simulate_rules` build the `last_changed` map once per run and
pass it to the evaluator next to `entity_state`.

**Simulation** (`simulate_rules`, rules test page): every entity supplied in
the request's `entity_states` override is treated as changed at `now`
(fresh change); entities not overridden keep their DB `last_changed`;
`entered_at` is read from the DB snapshot regardless of any `alarm_state`
override. This lets the test page exercise both the ignored and the
fresh-change branches.

**Explain trace** gains, on `entity_state` nodes carrying the flag:
`changed_since_alarm_transition: true`, `last_changed`, `alarm_entered_at`,
and when the flag forces a false result, `reason` ∈
`{"changed_before_alarm_transition", "missing_last_changed", "missing_alarm_entered_at"}`.

**Validation** (`validate_when_node`): if present, the key must be a boolean;
otherwise `{"changed_since_alarm_transition": ["must be a boolean"]}`.

**Frontend:**

- `EntityStateNode.changed_since_alarm_transition?: boolean` +
  `isEntityStateNode` accepts it.
- `EntityStateValue.changedSinceAlarmTransition?: boolean`;
  `converters.ts` copies it DSL→RQB and emits the key RQB→DSL **only when
  true** so existing rule JSON stays byte-identical.
- `EntityStateValueEditor.tsx`: a `Checkbox` labelled
  "Only after alarm state change" with a `HelpTip`: *"Ignore this sensor if it
  was already in this state when the alarm entered its current state (e.g. a
  door left open before arming). It counts again the next time it changes
  into this state."*

**Interplay with existing operators:**

- `for`: the child is re-evaluated on every run; the flag simply participates.
- `not`: `not(entity_state + flag)` means "not (in state X and changed since
  transition)". Allowed, documented, not expected to be common.
- `{{trigger.*}}` (ADR-0088) and `RuleEntityRef` extraction are unaffected —
  `entity_id` is still where it was.
- Cooldown, stop groups (ADR-0084), circuit breaker: unaffected.

**Operational follow-through (not code):** after deploy, edit prod rules 2
(`pet sitter mode`) and 3 (`trigger`) and tick the flag on all five door
conditions in each. Leave the `input_boolean.*` conditions unticked.

## Acceptance Criteria

- [ ] **AC-1**: Given `entity_state` with `changed_since_alarm_transition: true`, an entity whose `last_state == equals` and whose `last_changed` is earlier than `entered_at`, when evaluated, then the condition is **false**; the same node without the flag is **true**.
- [ ] **AC-2**: Given the same node and an entity whose `last_changed` is later than `entered_at`, when evaluated, then the condition is **true**; `last_changed == entered_at` is **false**.
- [ ] **AC-3**: Given the flag and either `last_changed` or `entered_at` missing, when evaluated, then the condition is **false** and the explain trace `reason` is `missing_last_changed` / `missing_alarm_entered_at` respectively.
- [ ] **AC-4**: Given a rule `all(alarm_state_in[armed_away], any(A+flag, B+flag))` with A already `on` before arming, when the alarm transitions to `armed_away` and `run_rules` executes, then the rule does **not** fire; when B then changes to `on` (later `last_changed`), the rule fires exactly once; when A changes `off` then `on` after the transition, the rule fires again (R2, R3).
- [ ] **AC-5**: Given a rule mixing a flagged door condition with an unflagged `input_boolean` condition whose `last_changed` predates `entered_at`, when the door changes after the transition, then the rule fires (unflagged condition still level, R4).
- [ ] **AC-6**: Given a rule definition where `changed_since_alarm_transition` is a non-boolean, when submitted to the rules API, then validation fails with `when.…changed_since_alarm_transition: ["must be a boolean"]`; `true`, `false` and absent are accepted.
- [ ] **AC-7**: Given a flagged node, when explained, then the trace includes `changed_since_alarm_transition`, `last_changed`, `alarm_entered_at`, and `reason: changed_before_alarm_transition` when ignored.
- [ ] **AC-8**: Given the dispatcher evaluating a batch for a flagged rule, when the scoped repositories are built, then `entity_last_changed_map()` returns `last_changed` for every entity in the scoped state map from the **same** query (no additional `Entity` query per rule), and the arm-time false trigger from the Background table does not reproduce in a dispatcher-level test.
- [ ] **AC-9**: Given `simulate_rules` with an `entity_states` override for a flagged entity, when simulated, then the entity is treated as changed at `now` and the rule matches; a flagged entity **not** overridden and with a stale DB `last_changed` does not match.
- [ ] **AC-10**: Given the frontend converters, when a DSL node with the flag is converted to RQB and back, then the flag round-trips; a node without the flag (or with `false`) emits **no** `changed_since_alarm_transition` key.
- [ ] **AC-11**: Given `EntityStateValueEditor`, when the "Only after alarm state change" checkbox is toggled, then `handleOnChange` is called with `changedSinceAlarmTransition` set accordingly and the existing `entityId`/`equals` preserved.
- [ ] **AC-12**: The full existing backend and frontend suites pass unchanged (R6); `test_import_boundaries_rules_use_cases` stays green.

## Consequences

### Positive
- Arm-time false triggers from already-open sensors stop, for both the
  `trigger` and `pet sitter mode` rules, without touching the state machine.
- Per-condition granularity keeps level conditions level.
- A still-open door no longer re-fires the trigger rule on every
  return-to-armed after a bell cycle.
- The trace explains the ignore, so "why didn't it trigger?" is answerable
  from the rules test page.
- Zero migration, backwards-compatible JSON, small PR.

### Negative
- Two clock domains in one comparison (HA vs Latchpoint). Zero skew in prod;
  NTP dependency elsewhere.
- Door left open during the exit delay is silently unprotected until it
  cycles closed → open.
- The flag must be applied by hand to each door condition; forgetting one
  leaves that door on today's semantics.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| HA clock behind Latchpoint clock by more than the arm→open gap makes a genuine post-arm opening look pre-arm and it is ignored | Low (same host in prod) | High (missed intrusion until next cycle) | Document NTP requirement; future option to stamp HA `last_changed` with local receive time when skew is detected; `armed_since` sub-option does not help here |
| `unavailable → on` blip (HA restart, radio dropout) bumps `last_changed` on an ignored open door and fires the trigger | Low | Medium (false alarm, same as today's behaviour for an open door) | Follow-up: in `state_stream.py`, keep the existing `last_changed` when `old_state ∈ {unavailable, unknown}` and the new state equals the last known state |
| Door opened during exit delay and left open is ignored once armed | Medium (for households that walk out during the exit delay) | Medium | Author a plain notification rule "armed AND any door open → notify" (no code); later, `armed_since` reference or the ready-to-arm doc's exit-error handling |
| Operator forgets to tick the flag on one door condition | Medium | Low (that door keeps today's behaviour) | Post-deploy checklist above; rules test page shows the flag in the trace |
| `RuleEngineRepositories` default `lambda: {}` masks a wiring mistake (flag silently never matches) | Low | High | AC-8 asserts the dispatcher path supplies `last_changed`; AC-3 makes the miss visible in the trace as `missing_last_changed` |

## Implementation Plan

- [ ] Phase 1 — Backend evaluator: `conditions.py` (validate + eval + explain), `repositories.py` (two new defaulted callables + default impls), `rules_engine.py` (build `last_changed` map once per run; simulate override = changed now). Tests: `test_rules_conditions.py`, `test_rules_engine.py`, `test_rules_repositories.py` (AC-1..AC-5, AC-7, AC-9).
- [ ] Phase 2 — Dispatcher: extend the scoped `values_list` in `_get_entity_state_map_for_rules` and wire both callables into the scoped `RuleEngineRepositories`. Test in `test_dispatcher_*` reproducing the incident shape (AC-8). Serializer validation test (AC-6).
- [ ] Phase 3 — Frontend: `types/ruleDefinition.ts`, `queryBuilder/types.ts`, `converters.ts` (+ tests, AC-10), `EntityStateValueEditor.tsx` (+ test, AC-11).
- [ ] Phase 4 — Lint/format/type-check, full suites (AC-12), PR, deploy `:main`, then tick the flag on prod rules 2 and 3 and confirm via the rules test page and the next real arm (`alarm_ruleactionlog` shows no fire within seconds of `armed`).

## Related ADRs

- [ADR-0004](./0004-rules-engine-entity-registry-remove-zones.md) — rules engine + entity registry; this ADR keeps the engine zone-free.
- [ADR-0057](./0057-integration-entity-updates-trigger-rules.md) — dispatcher; alarm transitions enter it as `__system.alarm_state`.
- [ADR-0059](./0059-rule-triggering-accuracy-and-realtime-semantics.md) — edge-on-WHEN semantics (`last_when_matched`) that this ADR refines per condition.
- [ADR-0061](./0061-optimize-dispatcher-entity-state-snapshot-for-rule-evaluation.md) — scoped entity-state snapshot the `last_changed` map rides on.
- [ADR-0084](./0084-user-named-stop-groups-for-rule-processing.md) — stop groups; the two affected prod rules share `stop_group="trigger"`.
- [ADR-0088](./0088-rule-message-template-variables.md) — `{{trigger.*}}` binding; unaffected.
- [ADR-0091](./0091-rule-action-entry-delay.md) — the 60 s PENDING in the incident timeline.
- [ADR-0102](./0102-change-only-entity-sync-writes.md) — `last_changed` write discipline on the poll path.
- [ADR-0104](./0104-burglar-siren-continuous-until-disarmed.md) — why an arm-time false trigger is loud until someone disarms.

## References

- `docs/planning/enhanced-sensors-ready-to-arm.md` — the broader Alarmo-style sensor model / ready-to-arm / bypass direction (Options 2 and 4 belong there).
- Home Assistant state object docs (`last_changed` vs `last_updated`): https://www.home-assistant.io/docs/configuration/state_object/
- Prod evidence: `alarm_alarmevent` and `alarm_ruleactionlog` rows for 2026-09-01 11:16 and 2026-09-03 11:15 (America/New_York).
