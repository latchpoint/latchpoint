# ADR-0094: Composable Rule-Action Primitives for Alarm and Control Panel (supersedes 0091)

**Status:** Proposed
**Date:** 2026-05-18
**Author:** Leonardo Merza

## Context

### Background

Latchpoint's rule engine controls alarm state and timing through a single
coupled action handler: `alarm_trigger`. With `delay_seconds: 0` it forces
the central state machine into `TRIGGERED`; with `delay_seconds > 0` it
enters `PENDING` for the delay window and queues a follow-up `TRIGGERED`
transition through the `PendingAction` scheduler. The Ring Keypad v2
mirrors the central alarm state via a Django signal receiver
(`alarm_state_change_committed` → `sync_ring_keypad_v2_devices_state()`),
so the keypad indicator (`_IND_ENTRY_DELAY`, `_IND_BURGLAR_ALARM`, …)
follows the alarm automatically.

[ADR-0091](0091-rule-action-entry-delay.md) (revised 2026-05-12) chose this
shape deliberately. Its argument was UX-driven: the alarm-state card and
the keypad both read `exit_at` from the snapshot to render an entry-delay
countdown. Queuing a bare `TRIGGERED` transition without first entering
`PENDING` would leave both surfaces blank during the wait. The schema
therefore collapsed "enter PENDING + queue TRIGGERED" into a single rule
action.

### Current State

- **`alarm_trigger` action handler**
  (`backend/alarm/rules/action_handlers/alarm_trigger.py:11-50`) — the only
  primitive that controls alarm state and timing from a rule. Accepts
  `delay_seconds` in `[0, 600]`.
- **`trigger_with_delay()` state-machine transition**
  (`backend/alarm/state_machine/transitions.py:254`) — internal entry point
  used exclusively by the handler. Forces `PENDING`, sets `exit_at`, and
  enqueues a `PendingAction` whose payload is `{"type": "alarm_trigger"}`.
- **`PendingAction` queue** (`backend/alarm/models.py:501-562`) — opaque
  `JSONField` payload, type-agnostic dispatch in
  `backend/alarm/tasks.py:338-398` (`_fire_one_pending_action`) via
  `get_handler(payload["type"])`. Already strips `delay_seconds` from the
  payload before re-dispatch.
- **`send_notification`** (`backend/alarm/rules/action_handlers/send_notification.py:38-65`)
  — the only other handler that carries a `delay_seconds`. Implements
  enqueue-or-execute inline.
- **`cancel_for_disarm`** (`backend/alarm/rules/pending_actions.py:87-99`)
  — cancels `PendingAction` rows whose `armed_state_at_schedule__in=ARMED_STATES`
  on disarm. Currently correct because `PENDING`/`ARMING`/`TRIGGERED` never
  appear as scheduling states — only `alarm_trigger` puts the state into
  `PENDING`, and it does so *before* the row is enqueued, so the row's
  `armed_state_at_schedule` is whatever armed state the schedule fired
  from.
- **Keypad sync** (`backend/control_panels/runtime.py:57-65` and
  `backend/control_panels/zwave_ring_keypad_v2.py:295-340`) — the Ring
  Keypad v2 has no concept of "follow but pause." It either mirrors the
  alarm or it doesn't. There is no per-panel override.
- **Frontend rule builder** — action types are hand-coded in
  `frontend/src/types/ruleDefinition.ts` (interfaces, type guards, union)
  and `frontend/src/features/rules/queryBuilder/ActionsEditor.tsx:33-41`
  (`ACTION_TYPES` array, field components). The backend exposes a schema
  registry via `get_action_schemas()`
  (`backend/alarm/rules/action_schemas.py:251`) but the frontend does not
  consume it dynamically.

### Requirements

Six months of usage have revealed authoring patterns that the coupled
primitive cannot express. Each requirement names a use case real users
have asked for:

1. **`PENDING` without an implicit `TRIGGERED`.** A rule that puts the
   alarm into `PENDING` and routes the follow-up action based on
   conditions evaluated *during* the pending window (e.g. send a
   notification, wait for a different sensor, only escalate on a second
   trip). Today's only way to enter `PENDING` from a rule is to queue
   a `TRIGGERED` follow-up — the two are inseparable.
2. **Control-panel state decoupled from alarm state.** Silent vacation
   mode where the alarm enters `PENDING` but the keypad stays dark;
   alternate-keypad-state UX where a side panel surfaces a different
   indicator than the central state.
3. **Customizable post-pending action.** "PENDING for 30 seconds, then
   `arm-vacation`" or "PENDING for 10 seconds, then `send-notification`"
   — the post-pending action is hardcoded to `TRIGGERED` today.
4. **Generic delay on any action.** "WHEN motion detected → wait 60s →
   turn off the porch light" — currently impossible without authoring
   two rules glued together on an intermediate alarm-state change.
5. **Trigger alarm vs. trigger panel as independent operations.** Today
   the keypad's burglar indicator can only light when the central alarm
   is in `TRIGGERED`. A rule cannot say "show the burglar indicator on
   panel 1 but leave the alarm armed."

### Constraints

- **Import boundary (ADR-0091 §Constraints).** `backend/alarm/rules/` and
  `backend/alarm/use_cases/` must not import from `backend/integrations_*`
  or `backend/transports_*`. New control-panel handlers route through a
  new app-level module `backend/control_panels/services.py`, which is
  allowed.
- **`PendingAction` schema is fixed.** The model is already type-agnostic;
  no schema migration is allowed as part of this work (it would force a
  larger blast radius).
- **State-machine invariants.** `previous_state`, `target_armed_state`,
  `timing_snapshot`, and `exit_at` are managed by the existing flows
  (`arm()`, `disarm()`, `sensor_triggered()`, `trigger_with_delay()`).
  Any new direct state setter must preserve them; see §Decision §3.2 for
  the per-transition treatment.
- **Existing rules must not break.** A reversible data migration must
  rewrite `{alarm_trigger, delay_seconds: N}` into the new composition
  transparently. Operators should not need to re-author rules.
- **Restart durability.** Queued actions survive backend restarts via
  `PendingAction.fire_at`. A composition that leaves the alarm in
  `PENDING` with a *cancelled* `alarm_trigger` (60s post-restart
  `STALE_AFTER_RESTART`) must not leave the state machine stuck — a
  recovery receiver is required.

## Options Considered

### Option A — Keep `alarm_trigger { delay_seconds }`; add only `control_panel_set_state`

Solves requirements 2 and 5. Leaves 1, 3, 4 unaddressed. Avoids touching
the state machine or the data migration. Smallest change.

**Rejected** because:
- Three of the five requirements would remain. The user's framing
  explicitly named all four decouplings as in-scope.
- The rule engine would have two delay patterns (per-handler vs.
  executor-level) indefinitely.
- The latent `cancel_for_disarm` bug (see §Decision §3.4) only surfaces
  once compositions exist; leaving the legacy path means the bug stays
  hidden behind a never-fired branch.

### Option B — Add a `wait` action that blocks the THEN sequence

A `{type: "wait", seconds: 30}` action that pauses the executor and
resumes the remaining actions after the timeout. Conceptually cleanest
for rule authors — the THEN list reads imperatively top to bottom.

**Rejected** because the executor cannot block:
- A synchronous block on the worker holds DB connections and stalls the
  rule queue.
- An asynchronous resume requires state-tracking for "partial THEN
  execution to be resumed later" — a new persistence concern (where do we
  store the cursor? how do we reconcile after a restart? how do we
  cancel mid-sequence?).
- The proposed generic `delay_seconds` on every action achieves the same
  expressivity by reusing the existing `PendingAction` queue. Order is
  declarative (each action carries its own delay) instead of imperative.

### Option C — Add a `schedule_action` that enqueues another rule's actions

`{type: "schedule_action", target: "rule:5:then[2]", delay: 30}`.
Cross-rule scheduling primitive.

**Rejected** because rule references become stringly-typed: deleting or
renaming the target rule would silently break the scheduler. Introduces
a new cross-rule dependency graph that has to be maintained, validated,
and surfaced in the UI.

### Option D — Keep legacy coupling; add `alarm_set_state` as a parallel API

Leave `alarm_trigger { delay_seconds }` intact, add the new primitives
alongside, skip the data migration.

**Rejected** because:
- Two ways to express the same behavior is confusing for rule authors
  and reviewers.
- The latent `cancel_for_disarm` bug (§3.4) remains hidden — the
  composition path is what exposes it, and operators using only the
  legacy primitive would not benefit from the fix.
- Operator-stated preference: "Replace `alarm_trigger` entirely." (See
  user thread 2026-05-18.)

### Option E — Per-rule override flag for keypad auto-mirror

`{control_panel_action: …, override_alarm_sync: true}` would suppress the
auto-mirror only for the duration of the action.

**Rejected** because two rules can both set the same panel: which one
"owns" the override? A per-panel `follow_alarm_state` flag on the
`ControlPanelDevice` row plus an explicit `state="auto"` resume action
gives a clear owner — whichever rule last wrote the panel owns it until
disarm (or until another rule writes `auto`). This matches operator
mental models ("I took this panel offline; I'll put it back online").

### Option F (chosen) — Composable primitives + generic executor delay + per-panel decoupling

Detailed in §Decision below. Replaces `alarm_trigger`'s embedded
`delay_seconds` with executor-level delay, adds four explicit handlers,
decouples the keypad via a per-panel flag, and migrates existing rules
to the new composition.

## Decision

Adopt **Option F**. The rule-action surface becomes:

### 3.1 Four explicit action handlers

| Handler | Parameters | Effect |
|---|---|---|
| `alarm_set_state` | `state` ∈ {`pending`, `triggered`, `disarmed`, `armed_home`, `armed_away`, `armed_night`, `armed_vacation`}, optional `delay_seconds` | Sets the central alarm state directly. `PENDING` does **not** auto-advance (no `exit_at` written). `ARMING` is rejected — use `alarm_arm` for the multi-step arming flow. |
| `alarm_trigger` (rewritten) | (no params) | Forces `TRIGGERED`. **Rejects** `delay_seconds` at validation time. To express an entry delay, compose with `alarm_set_state(pending)` and a delayed `alarm_trigger`. |
| `control_panel_set_state` | `panel_id`, `state` ∈ {`pending`, `disarmed`, `armed_stay`, `armed_away`, `triggered`, `auto`}, optional `countdown_seconds`, optional `delay_seconds` | Drives a specific keypad's Indicator CC. Flips `ControlPanelDevice.follow_alarm_state` to `False`. `state="auto"` flips it back to `True` and re-syncs from the alarm snapshot. |
| `control_panel_trigger` | `panel_id`, optional `delay_seconds` | Drives the burglar indicator on a specific keypad. Flips `follow_alarm_state=False`. Named symmetrically with `alarm_trigger` so rule authors can pick the right scope at a glance. |

All four handlers self-register in `backend/alarm/rules/action_handlers/`
and are added to the import block in `__init__.py`. The
`control_panel_*` handlers import from `backend/control_panels/services.py`
(new module) — keeping the import-boundary invariant intact.

### 3.2 State machine: new public `set_state(new_state, *, reason, user=None, exit_at=None, metadata=None)`

In `backend/alarm/state_machine/transitions.py`, exported alongside
`arm()` / `disarm()`. Guard table:

| From → To | Allow | Behavior |
|---|---|---|
| any → `PENDING` | yes | `exit_at` defaults to `None` (no auto-advance via `timer_expired()`). `previous_state` set via `set_previous_armed_state()` so a return-from-triggered has a sensible target. |
| any → `TRIGGERED` | yes | Subsumes legacy `trigger()`. From `DISARMED`, `previous_state` is `DISARMED`; the return-from-triggered loop (`timer_expired()` line 207) returns to `DISARMED`. |
| any → `DISARMED` | yes | Delegates to existing `disarm()` to preserve cleanup of `target_armed_state` and `timing_snapshot`. |
| any → `ARMED_*` | yes | Bypasses arming flow; loads active profile and resets `target_armed_state=None`, `timing_snapshot=base_timing(profile)`. |
| any → `ARMING` | reject | Raises `TransitionError("Use arm() — ARMING needs target_armed_state setup")`. The arming flow is multi-step; exposing it as a single setter would corrupt `target_armed_state`. |

The legacy `trigger()` becomes a one-line `set_state(TRIGGERED, …)`
wrapper. `trigger_with_delay()` is **deleted** in the rollout's PR 4 —
its only callers were `alarm_trigger.py:26` and the `AlarmServices`
protocol method, both removed by the same PR.

### 3.3 Generalized executor-level delay

The "enqueue if `delay_seconds > 0` else execute now" branch lifts from
`send_notification.py` and `alarm_trigger.py` into
`backend/alarm/rules/action_executor.py`. For every action with a valid
positive integer `delay_seconds`:

```text
pa = enqueue_pending_action(rule=rule, action_index=idx,
                             action_payload=action,
                             delay_seconds=action["delay_seconds"],
                             ctx=ctx)
action_results.append({"ok": True, "type": action_type, "deferred": True,
                        "pending_action_id": pa.id,
                        "fire_at": pa.fire_at.isoformat(),
                        "delay_seconds": action["delay_seconds"]})
continue
```

Validation of `delay_seconds` also lifts: a `_validate_delay_seconds`
helper in `backend/alarm/rules/action_schemas.py` runs as a final pass on
every action regardless of `type`. The `bool`-is-`int` Python footgun
(`True` is `1`) is rejected explicitly. `ALARM_TRIGGER_MAX_DELAY_SECONDS`
(currently 600) is renamed `ACTION_MAX_DELAY_SECONDS`; an alias remains
for one release to soften any out-of-tree imports.

The scheduler-side dispatch (`_fire_one_pending_action`) is unchanged.
It already strips `delay_seconds` before re-dispatch, so deferred actions
never re-enqueue themselves.

### 3.4 `cancel_for_disarm` filter fix

`backend/alarm/rules/pending_actions.py:87-99` currently filters:

```python
qs = PendingAction.objects.filter(
    status=PendingActionStatus.SCHEDULED,
    armed_state_at_schedule__in=list(ARMED_STATES),
)
```

Under the new composition, `[alarm_set_state(pending), {delay:N, alarm_trigger}]`
schedules the second action while the snapshot is already `PENDING` — so
its `armed_state_at_schedule` is `PENDING`, not an armed state. Today's
`in=ARMED_STATES` filter would skip cancellation on disarm, stranding
the queued trigger.

Fix:

```python
qs = PendingAction.objects.filter(
    status=PendingActionStatus.SCHEDULED,
).exclude(armed_state_at_schedule=AlarmState.DISARMED)
```

Semantically: cancel anything that wasn't scheduled while disarmed. The
existing comment block (pending_actions.py:89-94) already describes the
inverse correctly — "rows scheduled while DISARMED are left alone." The
current `in=ARMED_STATES` formulation happens to be equivalent only
because `PENDING`/`ARMING`/`TRIGGERED` never appeared as scheduling
states until now.

### 3.5 Control-panel decoupling

- **Migration**: `backend/control_panels/migrations/0004_controlpaneldevice_follow_alarm_state.py`
  adds `follow_alarm_state = BooleanField(default=True)` to
  `ControlPanelDevice`. No data migration; default preserves legacy
  behavior for every existing panel.
- **Sync filter**: `sync_ring_keypad_v2_devices_state()` queryset adds
  `follow_alarm_state=True`. Panels under explicit rule control are
  skipped by the auto-mirror.
- **Merged receiver**: the two `alarm_state_change_committed` receivers in
  `backend/control_panels/runtime.py` are merged into a single one. On
  transition to `DISARMED`, flip `follow_alarm_state=True` for all
  panels, then call `sync_ring_keypad_v2_devices_state()` once. This
  gives deterministic ordering (flag flip *before* sync) and is
  idempotent (re-flipping `True` is a no-op).
- **Manual resume**: `control_panel_set_state(panel_id, state="auto")`
  flips the flag back without requiring disarm.
- **Indicator service**: `backend/control_panels/services.py:apply_panel_state(panel_id, state, countdown=None)`
  and `resume_auto(panel_id)` expose the keypad-write logic to rule
  handlers without forcing a direct import of
  `backend/control_panels/zwave_ring_keypad_v2.py` from
  `backend/alarm/rules/`.

### 3.6 Pending-action stale-cancel recovery

`backend/alarm/tasks.py:415-425` cancels `PendingAction` rows with
`PendingActionCancelReason.STALE_AFTER_RESTART` when more than 60s past
`fire_at`. Under the new composition, a queued `alarm_trigger` cancelled
post-restart would leave the alarm stuck in `PENDING` with no further
scheduled transition.

Mitigation: a new receiver listens for stale cancellations and, if the
payload `type == "alarm_trigger"`, calls
`set_state(snapshot.previous_armed_state, reason="pending_action_stale")`
to recover. Implemented in PR 4 alongside the migration.

### 3.7 Data migration

`backend/alarm/migrations/0020_rewrite_delayed_alarm_trigger.py`
(`RunPython`, reversible). For every `Rule`, scan `definition["then"]`
for `{type: "alarm_trigger", delay_seconds: N>0}` and replace each in
place with the pair:

```json
{"type": "alarm_set_state", "state": "pending"}
{"type": "alarm_trigger", "delay_seconds": N}
```

The reverse migration collapses the pair back. A post-migration
assertion test fails the deploy if any `alarm_trigger` action retains
`delay_seconds`. No seed-data edits required —
`backend/alarm/management/commands/seed_test_home.py:379,395` already
uses bare `{"type": "alarm_trigger"}` with no delay.

### 3.8 Frontend

- `frontend/src/types/ruleDefinition.ts` — three new action interfaces
  (`AlarmSetStateAction`, `ControlPanelSetStateAction`,
  `ControlPanelTriggerAction`), type guards, union extension. Existing
  `actionHasValidDelay`/`hasActionLevelDelay` helpers gain support for
  the new types.
- `frontend/src/features/rules/queryBuilder/ActionsEditor.tsx` — extend
  `ACTION_TYPES` (line 33), add three field components, extract a shared
  `DelaySecondsField` rendered for every action row (currently
  duplicated between `AlarmTriggerFields` and
  `NotificationDelayField`).
- `frontend/src/hooks/useControlPanels.ts` — add
  `useControlPanelsListQuery()` so the rule builder can render a
  panel-id dropdown for the two new control-panel actions.
- UI tooltips warn about: (i) `alarm_set_state(pending)` alone shows no
  countdown on the dashboard or keypad (no `exit_at`); (ii)
  `control_panel_set_state` does not affect the alarm — the panel will
  not snap back until disarm or `state=auto`.
- `AlarmStateCard` renders `"PENDING (manual)"` badge with a tooltip
  when `exit_at` is null, surfacing the new state shape to operators.

### 3.9 Supersession of ADR-0091

[ADR-0091](0091-rule-action-entry-delay.md) is marked `Superseded by
ADR-0094 (2026-05-18)`. Its core trade-off — "implicit `PENDING` for
keypad UX" — is replaced by the explicit primitive model. Operators
who want the legacy "alarm card shows a countdown plus keypad entry
delay plus eventual trigger" UX now express it as a composition:

```json
[
  {"type": "alarm_set_state", "state": "pending"},
  {"type": "control_panel_set_state",
   "panel_id": <each_enabled_panel>, "state": "pending",
   "countdown_seconds": 30},
  {"type": "alarm_trigger", "delay_seconds": 30}
]
```

The data migration produces the first and third actions automatically;
operators who want the keypad countdown add the middle action via the
rule builder. A frontend "Entry Delay Flow" template inserts all three
by default to keep the common case ergonomic.

## Consequences

### Positive

- **Composable primitives match operator mental models.** Each primitive
  does one thing; behavior is the composition.
- **Every action becomes deferrable.** Generic `delay_seconds` unblocks
  "wait N seconds, then anything" rules without per-handler plumbing.
- **The `cancel_for_disarm` correctness fix lands.** Even rules that
  don't use the new primitives benefit.
- **Control-panel decoupling enables new UX patterns** — silent vacation
  mode, alternate-keypad indicators, panels-as-status-displays.
- **The data migration is reversible.** A rollback re-collapses
  compositions.
- **The state machine gains a public `set_state()` API** that's useful
  beyond rules (e.g. admin actions, scripted tests, future use-case
  primitives).
- **No `PendingAction` schema migration.** The model was already
  type-agnostic; the generalization is a 12-line lift in the executor.

### Negative

- **Bigger rule definitions.** A "30-second entry delay" goes from one
  action to three (alarm-pending + panel-pending + delayed-trigger).
  Mitigation: frontend "Entry Delay Flow" template.
- **`PENDING` without `exit_at` is a new state shape.** Dashboard
  countdown card, alarm-state card, and Z-Wave indicator all silently
  no-op for a manual `PENDING`. Mitigation: `AlarmStateCard` renders
  `"PENDING (manual)"` badge + tooltip, and the new ADR documents the
  caveat for rule authors.
- **`TRIGGERED` from `DISARMED` is now expressible.** Operator-authored;
  potentially surprising. The keypad's burglar indicator can light
  while the alarm is ostensibly "disarmed." Documented in ADR.
- **Keypad in `PENDING` while alarm `DISARMED` is now expressible.**
  Legitimate decoupling, but confusing. UI tooltip and ADR call it out;
  a future rule-linter check could flag the combination.
- **Two rules racing on the same panel** produce last-write-wins
  flickering on the Z-Wave bus. Same limitation as today's auto-sync
  against rapid alarm transitions; documented.
- **Larger test surface** (~250 LOC of new tests). Justified by the
  gain in expressivity and the regression coverage for the
  `cancel_for_disarm` fix.
- **Rule authors must understand composition.** Mitigation: tooltips,
  templates, and the "Entry Delay Flow" preset.
- **Generic `delay_seconds` on `alarm_arm` / `alarm_disarm`** is now
  allowed by the executor (operator authored it). Surfacing this with a
  warning chip in the UI is a follow-up; the underlying primitive is
  defensible (operator chose it).

### Neutral

- **No new dependencies.** No new env vars. Settings storage unchanged
  ([ADR-0079](0079-db-backed-config.md) preserved).
- **No frontend type generation.** Schemas remain hand-written in
  TypeScript; the registry pattern stays unchanged.
- **Cooldown anchor is unchanged.** Rule cooldown anchors at WHEN-match
  moment, not at deferred-action fire moment. Same as today's
  `send_notification` delay behavior; documented.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Alarm stuck in `PENDING` after backend restart cancels the queued trigger | §3.6 receiver: on `STALE_AFTER_RESTART` of an `alarm_trigger` payload, `set_state(previous_armed_state, reason="pending_action_stale")`. |
| Operator confusion when `alarm_set_state(pending)` shows no countdown | UI tooltip + ADR documentation; `AlarmStateCard` renders "PENDING (manual)" badge for `exit_at=null`. |
| Two `alarm_state_change_committed` receivers race on disarm | §3.5 single merged receiver: flag flip → sync, deterministic ordering. |
| Panel auto-sync clobbers explicit rule control during transaction interleave | `transaction.atomic` + `select_for_update` on the panel row + `transaction.on_commit` boundary for the indicator write. |
| Data migration corrupts complex rules | Reversible migration; post-migration assertion test; manual backup-restore drill before PR 4 deploy. |
| Rule authors forget to add the panel action and lose the keypad countdown | Frontend "Entry Delay Flow" template inserts all three actions by default. |
| Generic `delay_seconds` on `alarm_arm` / `alarm_disarm` produces surprising scheduling | Allowed by the executor (operator authored it); UI warning chip on these handlers. |
| Cooldown still anchors at WHEN-match, not at deferred-action fire | Documented in ADR; same as today's `send_notification` delay behavior. |

## Migration Plan

5 PRs, each independently shippable:

| PR | Scope | Operator-visible change | Migration? |
|---|---|---|---|
| 1 | Lift `delay_seconds` into executor; fix `cancel_for_disarm` filter; rename constant | None (refactor) | No |
| 2 | Add `set_state` + `alarm_set_state` handler + frontend | New action type available | No |
| 3 | Add `follow_alarm_state` field; `control_panel_set_state`; `control_panel_trigger` | Two new action types + decoupling | Schema migration only |
| 4 | Retire `alarm_trigger.delay_seconds`; data-migrate existing rules; delete `trigger_with_delay()`; stale-cancel recovery receiver | Existing delayed-trigger rules become 2-action compositions; one-time UI banner explains the rewrite | Reversible data migration |
| 5 | Cleanup; `AlarmStateCard` manual-PENDING UI | Manual `PENDING` shows distinct badge | No |

Rollback strategy: PRs 1-3 are additive and revertible. PR 4's data
migration has a working reverse (collapses the pair back into a single
delayed `alarm_trigger`). PR 5 is UI + dead-code removal.

## Decision on `alarm_trigger.delay_seconds` (resolved)

The two options considered:

- **(a)** **Rejected** by `_validate_alarm_trigger` — forces operators to
  write the explicit composition. Aligns with "no implicit timing on
  `alarm_trigger`."
- **(b)** **Accepted** via the generic executor queue — defers
  `TRIGGERED` N seconds with no intermediate `PENDING`.

**Decision: (a).** `alarm_trigger` is a pure "force TRIGGERED now"
primitive and rejects `delay_seconds` at the validator. The composable
replacement for the legacy `{alarm_trigger, delay_seconds: N}` shape is:

```json
[
  {"type": "alarm_set_state", "state": "pending"},
  {"type": "alarm_set_state", "state": "triggered", "delay_seconds": N}
]
```

Both halves use `alarm_set_state`; the executor's generic delay machinery
defers the second half via `PendingAction`. The data migration in §3.7
emits this exact shape, so existing rules transparently migrate without
operator intervention.

Implementation notes:

- The validator returns the error message
  `"alarm_trigger does not accept delay_seconds; compose with alarm_set_state(state='pending') and a delayed alarm_set_state(state='triggered') instead"`
  so authors get an actionable hint instead of a generic "bad field"
  error.
- The stale-cancel recovery receiver in `backend/alarm/tasks.py` keys on
  `action_payload__type="alarm_set_state"` + `action_payload__state="triggered"`
  (rather than `action_payload__type="alarm_trigger"`) to find the
  post-pending follow-ups that need recovery after a restart-during-
  PENDING.
- The frontend rule-builder UI for `alarm_trigger` has no expandable
  fields — there is nothing to configure.

Rationale: the whole point of the refactor is explicit composability.
Accepting `delay_seconds` on a "renamed only" `alarm_trigger` would
re-introduce a coupled-feeling primitive (silent `TRIGGERED` delay
without `PENDING`) just because the operator wrote it, and would split
the "PENDING entered" surface across two primitives. Decision (a) keeps
`alarm_trigger` semantically narrow.

## Todos

- [ ] PR 1: executor-level delay + `cancel_for_disarm` fix (no operator-visible change).
- [ ] PR 2: `set_state` state-machine API + `alarm_set_state` handler + frontend rows.
- [ ] PR 3: `follow_alarm_state` migration + `control_panel_set_state` + `control_panel_trigger` + decoupled receiver.
- [ ] PR 4: data migration + retire `alarm_trigger.delay_seconds` + stale-cancel recovery + rewrite affected tests.
- [ ] PR 5: cleanup + `AlarmStateCard` "PENDING (manual)" UI.
- [ ] Add frontend "Entry Delay Flow" template after PR 4.
- [ ] Update ADR-0091 status header to `Superseded by ADR-0094` once this ADR is Accepted.

## References

- [ADR-0079](0079-db-backed-config.md) — DB-backed config (unchanged; settings storage out of scope).
- [ADR-0091](0091-rule-action-entry-delay.md) — Rule action entry delay (superseded by this ADR).
- `backend/alarm/state_machine/transitions.py` — state machine.
- `backend/alarm/state_machine/snapshot_store.py` — snapshot persistence.
- `backend/alarm/rules/action_executor.py` — executor.
- `backend/alarm/rules/action_schemas.py` — schema registry + validation.
- `backend/alarm/rules/pending_actions.py` — queue API.
- `backend/alarm/models.py:501-562` — `PendingAction` model.
- `backend/alarm/tasks.py:338-398` — scheduler dispatch.
- `backend/control_panels/runtime.py` — keypad signal receiver.
- `backend/control_panels/zwave_ring_keypad_v2.py` — keypad Indicator CC writes.
- `frontend/src/features/rules/queryBuilder/ActionsEditor.tsx` — rule-builder action rows.
