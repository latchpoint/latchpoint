# ADR-0096: Scheduled Ticker for Alarm Exit/Entry-Delay Timers

**Status:** Implemented
**Date:** 2026-05-28
**Author:** Leonardo Merza

## Context

### Background

The alarm state machine has three time-delayed transitions, all keyed off an
`exit_at` timestamp stored on the single `AlarmStateSnapshot` row:

- **`arming → armed_*`** — the exit-delay countdown after `arm()` (`backend/alarm/state_machine/transitions.py:18-64`).
- **`pending → triggered`** — the entry-delay after an entry-point sensor trips or a rule-driven delay (`sensor_triggered()`, `trigger_with_delay()` per [ADR-0091](0091-rule-action-entry-delay.md)).
- **`triggered → previous_armed_state / disarmed`** — the auto-clear / `disarm_after_trigger` timeout.

All three are advanced by `timer_expired()` (`transitions.py:158-215`), which is a
*pull* operation: it only runs when something calls
`get_current_snapshot(process_timers=True)`.

### Current State (the bug)

`timer_expired()` / `tick_alarm_timers()` (`backend/alarm/use_cases/process_timers.py:17`)
is invoked only from:

- `GET /alarm/state` (`backend/alarm/views/alarm_state.py`),
- rule-action execution (`backend/alarm/rules/action_executor.py`, `pending_actions.py`).

The `process_alarm_timers` management command exists but was **never registered as a
scheduled task**, and no other periodic task ticks it (`process_due_rule_runtimes`
early-returns when no rule runtimes are due). The dashboard updates via WebSocket
*push* (broadcast on transition), not by polling `GET /alarm/state`, so even an open
client does not advance the timer once it has loaded.

Net effect: when the user arms and leaves — app backgrounds, WebSocket drops — nothing
reads state, so the single snapshot row stays at `current_state='arming'` with a past
`exit_at`. It only advances at the next state read, which in practice is the user's
**disarm on return**: that lazily fires `armed_away` then immediately `disarmed`.

### Observed incident

Prod (`docker-latchpoint-1`) Home Assistant mirror `alarm_control_panel.latchpoint_alarm`
showed `arming` for 10–56 minutes across six consecutive cycles (2026-05-26 → 2026-05-28),
each ending with `armed_away` and `disarmed` recorded 0.1–2.5 s apart — the fingerprint of
both publishes landing at disarm time. Reproduced live: armed with a 60 s exit delay, stuck
in `arming` for 2+ minutes until a state read. The HA lag was a faithful mirror; the real
defect was the DB-side transition never firing.

### Why this is a safety bug, not cosmetic

While stuck in `arming`, rule evaluation could not see an armed state. `_get_alarm_state()`
(`backend/alarm/rules/repositories.py`) filtered `exit_at__isnull=True`; the stuck row has a
non-null `exit_at`, so the lookup returned `None`. `ARMED_STATES` excludes `arming`, so any
intrusion rule gated on `alarm_state_in [armed_away, …]` evaluated **False** for the entire
away window — the alarm provided no protection. The same lazy gap applies to the
`pending → triggered` entry-delay: an intruder walking in would not auto-trigger until a
state read.

### Requirements

- Exit/entry-delay transitions must advance on their own within ~1 s, with no client read.
- The fix must survive process restarts and require no external infrastructure (matches the
  in-process scheduler of [ADR-0024](0024-in-process-task-scheduler.md)).
- Rule evaluation must never be blind to the true state during a timer window.
- A regression that re-stalls timers should be observable, not silent.

### Constraints

- `AlarmStateSnapshot` is a single mutated row; `timer_expired()` already runs inside
  `@transaction.atomic` with `select_for_update` and re-checks `exit_at` under the lock.
- The scheduler runs one thread per task; a 1 s task must do near-zero work when idle.

## Decision

1. **Register `process_alarm_timers` as `Every(seconds=1)`** in `backend/alarm/tasks.py`,
   reusing the existing `tick_alarm_timers()` use case. The body does a cheap, non-locking
   pre-check (`AlarmStateSnapshot.objects.filter(exit_at__lte=now).first()`) and only calls
   `tick_alarm_timers()` (which takes the row lock) when a timer is actually due. No
   `enabled_when` gate — this is core alarm logic, always on.
2. **Emit a stuck-timer warning.** When the ticker advances a timer that was overdue by more
   than `STUCK_TIMER_WARN_SECONDS` (5 s), it logs a `WARNING`. Under the 1 s cadence the
   overdue should be ≤ ~1–2 s, so a larger gap flags a regression rather than normal drift.
3. **Drop the `exit_at__isnull=True` filter** in `_get_alarm_state()`
   (`backend/alarm/rules/repositories.py`) so rule evaluation reads the true current state,
   including `arming`/`pending`. Defense-in-depth even after the ticker shrinks the window to ~1 s.
4. **Keep `timer_expired()` unchanged** and keep the `process_alarm_timers` management command
   for manual/one-off use. Only the invocation *cadence* was missing.

## Alternatives Considered

### Precise per-arm one-shot timer (asyncio / Channels)

Schedule a callback at exactly `exit_at` when entering `arming`/`pending`.

Pros: second-accurate; no idle polling.
Cons: a new mechanism with new failure modes; must reschedule every pending timer on each
process boot (otherwise a restart mid-countdown drops it); more code than the project needs.
The 1 s ticker already bounds imprecision to ~1 s, which is immaterial for a home exit delay.

### Coarser cadence (`Every(seconds=2)` or more), reuse an existing task

Pros: fewer wakeups; could piggyback on `fire_due_pending_actions` (2 s).
Cons: doubles worst-case exit-delay imprecision; coupling alarm-timer correctness to a task
about a different concern (PendingAction firing) is a foot-gun. A dedicated 1 s task with an
idle pre-check is cheap (one indexed lookup) and keeps the responsibility clear.

### Leave timers lazy; make the frontend poll `GET /alarm/state`

Pros: no backend task.
Cons: only works while a client is open and polling — exactly the condition that fails when
the user arms and leaves. Pushes a safety-critical guarantee onto the client. Rejected.

### Also fix `_get_alarm_state` by special-casing `arming`/`pending`

Map a pending timer to its `target_armed_state` instead of returning the literal state.
Cons: hides the real state from rules that legitimately want to act on `arming`/`pending`,
and re-introduces a translation layer. Returning the true state is simpler and correct.

## Consequences

### Positive

- Exit/entry-delay transitions fire within ~1 s unattended; the alarm actually arms and
  triggers without a client. Closes the no-protection-while-away window.
- Rule evaluation sees the real state during timer windows.
- A re-stalled timer surfaces as a `WARNING` instead of silently disabling the alarm.
- No new env var or infrastructure; uses the existing in-process scheduler.

### Negative / Risks

| Risk | Mitigation |
|---|---|
| A 1 s task adds wakeups and scheduler log lines. | The idle path is one indexed `exists`-style lookup and returns `{"processed": False}` without a lock. Comparable to the existing 2 s tasks (`fire_due_pending_actions`, `broadcast_system_status`). |
| Dropping the `exit_at__isnull` filter changes what rules see during a legit (brief) countdown. | Intended. Armed-state-gated rules still evaluate False during `arming` (it is not in `ARMED_STATES`); only rules explicitly gated on `arming`/`pending`/`triggered` change behavior, which is what those authors want. The filter dated to the initial commit with no test pinning it. |
| Tick races with a concurrent disarm/read. | `timer_expired()` re-checks `exit_at` under `select_for_update`; the pre-check → tick gap is benign (worst case: one no-op tick). |

### Neutral

- `process_alarm_timers` management command stays for manual invocation.
- HA MQTT mirror lag disappears as a side effect — it was always a faithful mirror of the
  (previously stuck) DB state, not an independent bug.

## Implementation Plan

1. `backend/alarm/tasks.py`: add `STUCK_TIMER_WARN_SECONDS = 5`; register
   `process_alarm_timers` at `Every(seconds=1)` with the idle pre-check and stuck warning.
2. `backend/alarm/rules/repositories.py`: remove the `exit_at__isnull=True` filter in
   `_get_alarm_state()`.
3. Tests: `backend/alarm/tests/test_process_alarm_timers_task.py` (unattended advance for
   arming→armed and pending→triggered, idle no-op, stuck warning) and
   `backend/alarm/tests/test_rules_repositories.py` (`get_alarm_state` returns the real state).
4. `uvx ruff check backend/` + `uvx ruff format --check backend/`; `./scripts/docker-test.sh`.

## Acceptance Criteria

- [x] AC-1: `process_alarm_timers` is registered with `Every(seconds=1)` and discovered at app start.
- [x] AC-2: With a past `exit_at` in `arming`, calling the task (no `GET /alarm/state`) advances to `armed_away`.
- [x] AC-3: With a past `exit_at` in `pending`, the task advances to `triggered`.
- [x] AC-4: With no due timer (future `exit_at` or disarmed), the task returns `{"processed": False}` and does not transition.
- [x] AC-5: A timer overdue by more than `STUCK_TIMER_WARN_SECONDS` logs a `WARNING`; a fresh overdue does not.
- [x] AC-6: `_get_alarm_state()` returns `"arming"` while a timer is pending (not `None`), and `"armed_away"` after it clears.
- [x] AC-7: `./scripts/docker-test.sh` passes.
- [x] AC-8: `uvx ruff check backend/` and `uvx ruff format --check backend/` clean.

## Related ADRs

- [ADR-0024](0024-in-process-task-scheduler.md) — the in-process scheduler this task registers with.
- [ADR-0091](0091-rule-action-entry-delay.md) — rule-driven entry-delay; its `pending → triggered` advance relies on `timer_expired()`, now ticked reliably.
- [ADR-0094](0094-composable-rule-action-primitives.md) / [ADR-0095](0095-deprecate-profile-timing-settings.md) — composable timing/action primitives that produce `exit_at`-based transitions.

## References

- `backend/alarm/state_machine/transitions.py:158-223` — `timer_expired()` / `get_current_snapshot()`.
- `backend/alarm/use_cases/process_timers.py:17` — `tick_alarm_timers()`.
- `backend/alarm/tasks.py` — new `process_alarm_timers` scheduled task + `STUCK_TIMER_WARN_SECONDS`.
- `backend/alarm/rules/repositories.py` — `_get_alarm_state()` filter removed.
- `backend/alarm/management/commands/process_alarm_timers.py` — manual command (unchanged).

## Todos

- None.
