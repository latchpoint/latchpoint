# ADR-0091: Rule Action Entry Delay via Unified PendingAction Queue

**Status:** Implemented
**Date:** 2026-05-12
**Author:** Leonardo Merza

## Context

### Background

Latchpoint already has a concept of an **entry delay** — a short grace
window between the moment a sensor trips and the moment the alarm goes off.
That mechanism is hardcoded to a sensor flag (`Sensor.is_entry_point`) and
the per-profile `delay_time` setting. When such a sensor opens while armed,
`sensor_triggered()` puts the state machine into `PENDING` for `delay_time`
seconds, then `timer_expired()` advances to `TRIGGERED` unless a disarm
intervenes.

The rules engine — which lets users author richer conditions ("WHEN front
door opens AND armed_away AND time is after 10pm") — has no equivalent
primitive. Today's `alarm_trigger` rule action fires immediately, and the
`send_notification` action has no delay either. Users have asked for both:

- **Entry delay on a rule** — "WHEN front door opens AND armed_away → wait
  15 seconds → trigger" — to give the homeowner time to disarm without
  being limited to the entry-point sensor flag.
- **Delayed notifications** — "WHEN motion detected → wait 30 seconds →
  notify" — as a heads-up window before escalation.

### Current State

- **Entry-point sensor flow** (`backend/alarm/state_machine/transitions.py`
  lines 111–154): only fires on a sensor trip, can't express a multi-clause
  rule.
- **`alarm_trigger` action handler** (`backend/alarm/rules/action_handlers/alarm_trigger.py`):
  three-line wrapper around `ctx.alarm_services.trigger(...)`; no delay
  support.
- **`send_notification` action handler**: synchronous dispatch via the
  notification provider; no delay support.
- **Scheduler app** (`backend/scheduler/`): thread-based in-process tasks
  registered via `@register(...)`; supports `Every(seconds=N)` and
  `DailyAt(...)` schedules. Already running tasks at 2-second cadence
  (`broadcast_system_status`).
- **Rules engine** (`backend/alarm/rules_engine.py`): reactive — runs on
  dispatcher batches (sensor events, alarm-state changes), not on a time
  tick. Already has a `for` operator that schedules-and-cancels with
  `RuleRuntimeState.scheduled_for` (rules_engine.py:127–215).
- **Signals**: `alarm_state_change_committed` fires via `transaction.on_commit`
  after every alarm state transition; receivers wire into it via
  `backend/alarm/receivers.py`.

### Requirements

- Per-rule, per-action delay configurable on `alarm_trigger` and
  `send_notification`.
- During the wait, the alarm stays in its current armed state — **no**
  forced transition into `PENDING`. A separate dashboard surface shows the
  countdown.
- Three cancellation triggers, all working uniformly:
  1. **Disarm** — disarming the alarm cancels every queued action that was
     scheduled while armed.
  2. **WHEN-condition false** — when the rules engine re-evaluates and a
     rule no longer matches its WHEN, cancel its queued actions.
  3. **Explicit operator cancel** — a UI/API affordance to cancel a queued
     action manually.
- Restart-durable: queued actions survive a backend reboot.

### Constraints

- `alarm/rules/` and `alarm/use_cases/` must NOT import from `integrations_*`
  or `transports_*` (enforced import boundary, CLAUDE.md).
- The user-chosen cancellation semantic — "WHEN-condition false cancels" —
  is the **opposite** of commercial alarm-panel entry-delay (where closing
  the door must NOT cancel the trigger, otherwise an intruder could exploit
  it). The user picked this deliberately for a home-lab context where brief
  door flickers shouldn't fire false alarms. A future
  `cancel_on_when_false: false` opt-out flag would let us recover
  classic-panel semantics if needed.

## Options Considered

### Option 1: Per-action `delay_seconds` routing through the existing PENDING state

**Description:** Extend the `alarm_trigger` action with a `delay_seconds`
field; when set, the handler calls a new `trigger_with_delay()` state-machine
helper that transitions the alarm to `PENDING` with
`exit_at = now + delay_seconds`. `timer_expired()` later advances to
`TRIGGERED`. The existing dashboard PENDING countdown UX is reused.

**Pros:**
- Reuses the existing PENDING state, `exit_at` field, `timer_expired()`
  advancement, and disarm-cancels-pending semantics.
- Best dashboard UX for `alarm_trigger`: the alarm card itself shows a
  countdown.

**Cons:**
- **Only solves `alarm_trigger`.** A delayed `send_notification` has no
  natural equivalent — PENDING is an alarm-state concept, not an action
  concept.
- Cancellation hooks are limited to what the state machine already provides
  (disarm, timer expiry). Adding WHEN-false cancellation requires a
  separate path that doesn't share semantics with the rest of the system.

### Option 2: Rely on `is_entry_point` + `delay_time`

**Description:** Tell users to tag sensors as entry points and configure
`delay_time` on the profile. No code changes.

**Pros:** zero code; the mechanism already works.

**Cons:** sensor-shaped, not rule-shaped. A rule like "door opens AND
after 10pm" can't be expressed by tagging a sensor — the rule's other
conditions are invisible to the sensor flag. Doesn't help `send_notification`.

### Option 3: Expose the `for` operator in the rules UI

**Description:** The backend already supports `WHEN <cond> FOR N seconds`
with correct cancellation; add the UI affordance to the query builder.

**Pros:** backend infrastructure exists, per-rule, composable.

**Cons:** **wrong cancellation semantic for entry delay**. `for` cancels
the moment the condition flips false — useful for debouncing flickery
sensors, but exactly opposite of what an alarm trigger needs (the user
wants a fixed window to enter their disarm code, not a window that
disappears as soon as they close the door). Also doesn't solve
`send_notification`.

### Option 4: Unified PendingAction queue (chosen)

**Description:** A new `PendingAction` model stores deferred actions. The
relevant handlers (`alarm_trigger`, `send_notification`) gain a
`delay_seconds` field; when set, they **enqueue** a row instead of
executing. A scheduler task at 2-second cadence fires due rows by
re-dispatching through the same handler registry. Three cancellation hooks
flip rows to `cancelled`. A dashboard card surfaces the queue with a
Cancel button.

**Pros:**
- One mechanism for both action types and any future action that wants a
  delay.
- DB-backed → restart durability for free.
- Cancellation is a model field flip, uniformly applied across all
  triggers.
- The rules engine's WHEN-false detection is a single existing code path
  (`rules_engine.py:225-231`); the queue cancellation hook attaches there.
- The disarm signal is already broadcast after every state transition; a
  new receiver listens for it.

**Cons:**
- The `alarm_trigger` countdown no longer appears on the alarm-state card —
  it lives on a separate Pending Actions card. A UX shift versus
  classic alarm panels.
- New model + migration + scheduler task + API + UI surface. Larger
  feature footprint than Option 1.
- Cooldown interaction is subtler: cooldown is keyed at enqueue time, not
  fire time, so a rule can't queue 10 actions in 10 seconds and have them
  all eventually fire.

## Decision

**Chosen Option: Option 4 — Unified `PendingAction` queue.**

Reasoning:
- The feature has to solve `send_notification` delays as well, and those
  have no PENDING-state analogue. A unified primitive avoids two parallel
  mechanisms.
- Restart durability (DB-backed) is a real correctness property for
  home-security software — losing a queued notification because of a Docker
  restart would be surprising.
- The three cancellation triggers compose naturally with a single status
  field; they don't have to reach into the state machine.
- The UX shift (countdown on a separate card) is honest about what's
  happening: the alarm isn't in PENDING for entry-delay reasons, it's
  staying armed while a rule's action waits in a queue.

## Consequences

### Positive

- **One mechanism, two action types.** Same enqueue, same fire path, same
  cancellation rules.
- **Restart durable.** A PendingAction queued before a reboot fires (or is
  auto-cancelled if older than 60s past `fire_at`) when the backend comes
  back.
- **Clean audit trail.** Every queued action has a `fire_result` plus a
  `status` + `cancel_reason` — easy to debug "why didn't this fire?".
- **Extension point.** Future action types can opt in by reading
  `delay_seconds` from their JSON payload and calling `enqueue_pending_action`.

### Negative

- **Cancellation requires events.** WHEN-false cancellation is event-driven
  — the rules engine runs only on dispatcher batches (sensor events, alarm
  state changes), not on a time tick. A rule whose WHEN flips false purely
  because of a `time_in_range` condition (no other event) won't cancel its
  queued action until something else triggers `run_rules()`. Most rules
  trip on sensor events that themselves trigger re-evaluation on close, so
  this should rarely matter; we'll document it and revisit if a user
  reports a concrete miss.
- **No PENDING countdown on the alarm card for rule-driven trigger delays.**
  Users used to commercial alarm-panel countdown displays might find this
  surprising. The Pending Actions card on the dashboard is the
  substitute.
- **`bool` validation gotcha.** Python's `bool` is a subclass of `int`,
  so validators must reject `delay_seconds: true` with an explicit
  `isinstance(value, bool)` check before the `isinstance(value, int)`
  check. This is captured in the schema validator and dedicated tests but
  worth documenting for any future int-valued schema field.
- **Cooldown semantics.** The rules engine's existing `cooldown_seconds`
  fires when an action is dispatched. For delayed actions, that dispatch
  is the **enqueue** moment, not the fire moment. This is the right choice
  (otherwise queued actions could pile up faster than they fire), but it
  means a rule with a 5-minute cooldown that queues a 4-minute-delayed
  trigger will be cooldown-locked for the duration of the wait + the
  cooldown.

### Security Considerations

- **Manual cancel of `alarm_trigger` requires a disarm code.** Cancelling a
  queued `alarm_trigger` PendingAction is functionally equivalent to disarming
  the alarm — it prevents the trigger from firing. To preserve the
  disarm-requires-code security property, `POST /api/alarm/pending-actions/<id>/cancel/`
  validates a `code` in the request body when the target row's
  `action_payload.type == "alarm_trigger"`. The same `validate_user_code()`
  helper used by `disarm_alarm()` is reused, so the failure modes (missing
  code → 400 `validation_error`; invalid code → 401 `unauthorized`) match the
  rest of the system. Other action types (`send_notification`) cancel without
  a code — they are not security-critical.
- **`fire_result` is API-visible.** When a handler raises, the persisted
  `fire_result["error"]` stores only the exception class name (e.g.,
  `"handler_exception"` + `"exception_class": "OperationalError"`), not the
  raw `str(exc)`. The full traceback stays in logs (`logger.warning` with
  `exc_info=True`). This avoids leaking internal hostnames / connection
  strings through the authenticated list endpoint.

### Neutral / Out of Scope

- Per-state delay overrides (e.g., different grace for `armed_home` vs.
  `armed_away`) remain available via the profile's `state_overrides` setting
  for the entry-point sensor flow. Rules using the new per-action
  `delay_seconds` are explicitly per-action; if a user wants different
  delays per arming state, they author two rules.
- We do **not** auto-add `delay_seconds` to other action types
  (`ha_call_service`, `zwavejs_set_value`, `zigbee2mqtt_*`, `alarm_arm`,
  `alarm_disarm`). YAGNI — those will opt in if and when a real use case
  appears.

## Implementation Notes

### New backend pieces

- **Model**: `PendingAction` (`backend/alarm/models.py`) with
  `rule` FK, `action_index`, `action_payload` (JSON snapshot), `delay_seconds`,
  `fire_at`, `status` (scheduled/fired/cancelled/failed), `cancel_reason`,
  `armed_state_at_schedule`, plus `fired_at`, `fire_result`, `actor_user`,
  `created_at`, `updated_at`. Indexes on `(status, fire_at)` and
  `(rule, status)`. Migration `0019_pendingaction.py`.
- **Enqueue helper**: `enqueue_pending_action()` in
  `backend/alarm/rules/pending_actions.py`. Captures
  `armed_state_at_schedule` from the current snapshot.
- **Handler changes**:
  - `backend/alarm/rules/action_handlers/alarm_trigger.py`: branches on
    `delay_seconds`. Result dict on enqueue includes `deferred: True`,
    `pending_action_id`, `fire_at`, `delay_seconds`.
  - `backend/alarm/rules/action_handlers/send_notification.py`: same
    pattern.
- **ActionContext.action_index**: new defaulted field on the frozen
  `ActionContext` dataclass. `action_executor.py` uses
  `dataclasses.replace(ctx, action_index=idx)` per iteration so the
  handler knows which slot it's in.
- **Schema**: `_validate_alarm_trigger` and `_validate_send_notification`
  accept optional `delay_seconds` int in `[0, 600]`, rejecting `bool`
  first; `get_action_schemas()` exposes the field on both.
- **Scheduler task**: `fire_due_pending_actions` in
  `backend/alarm/tasks.py`, `Every(seconds=2)`. Locks rows with
  `select_for_update(skip_locked=True)`, strips `delay_seconds` from the
  dispatched payload (so the handler doesn't re-enqueue), marks
  `fired` or `failed` with the handler's result. Rows past
  `PENDING_ACTION_STALE_THRESHOLD_SECONDS = 60` past their `fire_at` are
  auto-cancelled with `cancel_reason='stale_after_restart'`.
- **Cancellation hooks** (`backend/alarm/receivers.py`):
  - `alarm_state_change_committed → DISARMED`: cancels every `scheduled`
    row whose `armed_state_at_schedule` was armed.
  - `Rule.pre_delete`: cancels every scheduled row for the rule.
  - `Rule.post_save` with `enabled=False`: cancels every scheduled row for
    the rule.
- **Rules engine WHEN-false hook** (`backend/alarm/rules_engine.py:225-231`):
  inside the existing transition-to-not-matched block, calls
  `cancel_for_rule(rule.id, reason=WHEN_FALSE)`. Event-driven only —
  see the Consequences section about time-only conditions.
- **API** (`backend/alarm/views/pending_actions.py`):
  - `GET /api/alarm/pending-actions/?status=scheduled&limit=N`: list. `status`
    is validated against `PendingActionStatus.choices` + `"all"`; unknown
    values return 400. `limit` is clamped to `[1, 500]` (negative values would
    otherwise hit Django's slice and 500).
  - `POST /api/alarm/pending-actions/<id>/cancel/`: manual cancel. Requires
    a valid disarm `code` in the request body when the target action is
    `alarm_trigger` (see Security Considerations). 404s route through the
    domain `NotFoundError` → `custom_exception_handler` so the response uses
    the ADR-0025 envelope.

### New frontend pieces

- **TS types** (`frontend/src/types/alarm.ts`): `PendingAction`,
  `PendingActionStatusType`, `PendingActionCancelReasonType`.
- **TS action types** (`frontend/src/types/ruleDefinition.ts`):
  `AlarmTriggerAction.delaySeconds?: number` and
  `SendNotificationAction.delaySeconds?: number`. Type-guards validate
  0..600 integer.
- **Wire format**: camelCase in TS auto-snake_cases at the API boundary
  via `frontend/src/services/api.ts`'s `transformKeysDeep` — no bespoke
  serializer needed.
- **Builder UI** (`frontend/src/features/rules/queryBuilder/ActionsEditor.tsx`):
  `AlarmTriggerFields` and `NotificationDelayField` render an Entry-delay
  number input with 0..600 validation. Collapsed-row badges show
  "delay Ns" when set.
- **Service + hooks** (`frontend/src/services/alarm.ts`,
  `frontend/src/hooks/useAlarmQueries.ts`):
  `usePendingActionsQuery` with `refetchInterval: 2000`, plus
  `useCancelPendingActionMutation` with cache invalidation.
- **Dashboard card** (`frontend/src/components/dashboard/PendingActionsCard.tsx`):
  list of currently-scheduled actions with live countdown (1-second
  client-side ticker) and per-row Cancel button. Renders nothing when
  the queue is empty.

### Tests

- Backend `backend/alarm/tests/test_pending_actions.py`:
  - Enqueue paths for both action types (delay > 0 enqueues, delay 0 /
    missing executes immediately, bool/negative treated as zero,
    `armed_state_at_schedule` captured from snapshot).
  - Fire-due scheduler task: due rows fired, future rows untouched,
    terminal rows ignored, stale rows auto-cancelled, unsupported types
    marked failed.
  - Cancellation: disarm cancels armed scheduled rows but leaves disarmed
    rows alone; rule deletion CASCADEs; rule disable cancels; rule enable
    leaves alone; rules-engine WHEN-flips-false cancels; manual API cancel
    works.
  - API: list returns `data`-wrapped envelope, default filters to
    `scheduled`, `status=all` returns everything, cancel endpoint flips
    status, cancel of terminal row returns 404.
- Frontend `ActionsEditor.test.tsx`: send_notification delay round-trip
  (badge, emit, clear/zero strips, > 600 errors).
- Frontend `PendingActionsCard.test.tsx`: empty state renders nothing,
  list renders with countdown, cancel button calls mutation.

## Migration

None. Existing rules without `delay_seconds` keep working unchanged. New
rules opt in by setting the field. The `PendingAction` table starts empty.
No backfill required.
