# ADR-0103: Idle Scheduler and Ingest Quiet-Down

**Status:** Proposed
**Date:** 2026-07-21
**Author:** Leonardo Merza

## Context

### Background

GitHub issue [#80](https://github.com/latchpoint/latchpoint/issues/80): at
complete idle the deployment sustains ~3.4 queries/sec against tables holding
1–14 rows (~2.2M/week), ~6.5% baseline CPU on app and DB containers, and ~7
log lines/sec. The issue attributes the load to the 1–5s scheduler tasks
re-querying state tables every tick.

### Current State (investigated 2026-07-21 — the issue's attribution is partly wrong)

A code trace re-attributed the measured rates:

- **The settings-table reads do NOT come from the scheduler ticks.** The 2s
  `broadcast_system_status` path already reads settings through a cached
  module snapshot (`_settings_snapshot` in `backend/alarm/system_status.py`,
  invalidated by the `settings_profile_changed` signal) — zero DB reads at
  idle after warm-up. The ~0.64/s `alarm_alarmsettingsprofile` +
  ~1.29/s `alarm_alarmsettingsentry` scans instead come from the **MQTT
  ingest handlers**: `integrations_zigbee2mqtt/runtime.py` (`_handle_message`
  → `get_settings()` → `get_active_settings_profile()`) and
  `integrations_frigate/runtime.py` (same shape) re-read the active profile
  **on every inbound MQTT message** — 1 profile + 2 entry queries per
  message. Steady Zigbee device chatter (battery/linkquality reports) at
  ~0.64 msg/s produces exactly the measured 1:2 ratio. This load scales with
  device count, not with alarm activity.
- **Hidden per-run telemetry writes the issue missed:** every task run
  issues ~3 `scheduler_taskhealth` UPDATEs
  (`update_task_health_scheduling` / `_started` / `_finished_success` in
  `backend/scheduler/runner.py` + `telemetry.py`). The 1s
  `process_alarm_timers` alone contributes ~3 writes/s — more DB work than
  all the reads the issue tabulates. (`SchedulerTaskRun` rows are correctly
  only persisted for slow/failed runs.)
- **Guard coverage is inconsistent across the fast tasks:**
  - `process_alarm_timers` (1s) and `process_due_rule_runtimes` (5s)
    already have cheap single-query pre-checks.
  - `notifications_send_pending` (5s) runs a stale-reclaim UPDATE-filter +
    a locking batch SELECT **unconditionally** (2 queries/tick,
    `backend/notifications/tasks.py`).
  - `fire_due_pending_actions` (2s) runs a stale-cancel UPDATE-filter + a
    due SELECT **unconditionally** (2 queries/tick, ~1.0/s on
    `alarm_pendingaction` — a table the issue's list omits).
- **Idle log volume is exactly 3 INFO lines per run** from
  `backend/scheduler/runner.py` ("scheduled for" / "starting" /
  "completed in") — the task bodies are quiet on no-op ticks.
- **Environment constraints:** single daphne process in the shipped
  container (scheduler threads in-process); no `CACHES` config (per-process
  `LocMemCache`), in-memory Channels layer, no LISTEN/NOTIFY; the scheduler
  leader lock exists but defaults off. There is no cross-process
  invalidation or wake mechanism today.

### Requirements

- Eliminate the per-MQTT-message profile/entry reads (the dominant and
  device-count-scaled read load).
- Idle ticks of every fast task should cost at most one cheap query.
- Cut the per-run `scheduler_taskhealth` write load for sub-minute tasks
  without losing failure/slow-run observability.
- No INFO-level log lines for healthy no-op runs.
- No change to alarm-critical semantics: timer transitions, pending-action
  firing, notification retry behavior, and rule processing must be
  observably identical.

### Constraints

- `alarm/rules/` and `alarm/use_cases/` must not import `integrations_*` or
  `transports_*` (enforced boundary) — caches live in the integration
  modules, not in `alarm`.
- Caches are per-process and the invalidation signal is in-process; that
  matches the existing `_settings_snapshot` precedent and the shipped
  single-process deployment. Multi-replica deployments already accept this
  for status broadcasting.
- The scheduler status UI reads `SchedulerTaskHealth`; throttled writes may
  make its data up to ~60s stale for fast healthy tasks (up to ~2 windows for
  intervals just under 60s, since the window is stamped when the run is
  scheduled rather than when it finishes). Unhealthy runs must stay accurate:
  a hung task has to remain visible as `running`/`stuck`, which is why the
  throttle escalates on overdue runs rather than skipping their writes.

## Options Considered

### Option A: Targeted quiet-down (chosen)

**Description:** Four independent small fixes: (1) settings snapshot caches
for the Z2M and Frigate ingest handlers (copying the
`_settings_snapshot` + `settings_profile_changed` pattern), (2) cheap
`exists()` pre-guards in the two unguarded tasks, (3) a ~60s throttle on
`scheduler_taskhealth` writes for sub-minute tasks (failures/slow runs
always persist), (4) demote the three per-run runner log lines to DEBUG.

**Pros:**
- Each fix is independently small, testable, and revertable
- Addresses all three *corrected* problems: reads, hidden writes, logs
- No changes to alarm-critical timer semantics
- The ingest cache fixes a load that grows with Zigbee device count

**Cons:**
- Keeps ~1.5 cheap queries/s of residual polling (harmless: the issue
  itself concedes seq scans on 1–14-row tables are the planner's right
  choice)

### Option B: Option A + event-driven timer/pending wakes

**Description:** Additionally have writers (state transitions,
`enqueue_pending_action`) signal an in-process condition so
`process_alarm_timers` / `fire_due_pending_actions` sleep until the next
known due time, with a bounded fallback poll.

**Pros:**
- Near-zero idle queries — the fullest form of the issue's direction #2

**Cons:**
- Touches the alarm-critical timer path (arming→armed, pending→triggered)
  for marginal gain over Option A
- No cross-process invalidation exists; correctness leans on the
  single-process assumption plus a fallback poll — more machinery, larger
  test surface
- Scheduler runner needs per-task wake plumbing

### Option C: Logs + telemetry throttle only

**Description:** Only demote the per-run logs and throttle the health
writes; leave all queries as-is.

**Pros:**
- Tiny diff; fixes log noise and the hidden write load

**Cons:**
- Leaves the per-MQTT-message settings reads (the real finding) untouched
- Doesn't materially answer the issue

## Decision

**Chosen Option:** Option A — targeted quiet-down.

**Rationale:** The investigation showed the issue's headline number is
mostly *not* scheduler polling: the settings reads ride on MQTT ingest and
scale with device chatter, and the largest single DB load was hidden
telemetry writes. Option A fixes exactly what was measured, using a cache
pattern the codebase already trusts, without touching the safety-critical
timer path that Option B would rework for ~1.5 cheap queries/s of residual
benefit. Option C answers neither the read load nor the issue's intent.

### Design sketch

1. **Ingest settings caches** — in `integrations_zigbee2mqtt/runtime.py`
   and `integrations_frigate/runtime.py`: module-level normalized-settings
   snapshot behind a lock; `get_settings()` returns it, refreshing from DB
   only when empty; a `settings_profile_changed` receiver clears/refreshes
   it (register in each app's existing signal-wiring location, mirroring
   `system_status.py`). All profile writers already fire that signal via
   `transaction.on_commit` (verified: settings-profile use cases + all five
   integration settings views).
2. **Tick guards** —
   - `notifications_send_pending`: skip reclaim + batch when
     `NotificationDelivery.objects.filter(status__in=[SENDING, PENDING]).exists()`
     is false (1 cheap query at idle; unchanged behavior when work exists).
   - `fire_due_pending_actions`: skip stale-cancel + due-select when
     `PendingAction.objects.filter(status=SCHEDULED).exists()` is false.
3. **Telemetry throttle** — in `backend/scheduler/telemetry.py`: for tasks
   whose schedule interval is under ~60s, persist
   scheduling/started/finished-success health at most once per 60s window
   (in-process last-persisted map); always persist immediately on failure,
   slow run, or first run after startup. `update_task_health_finished_failure`
   stays unconditional.
   - **Escalate on overdue runs.** Skipping the `started` write would leave the
     DB-derived `running`/`stuck` status in `scheduler/views.py` blind to a hung
     sub-minute task, because both are gated on the row's `is_running`. The
     supervisor's existing stuck detector therefore also calls
     `persist_running_now()` once a run passes `max_runtime_seconds`, and
     `should_persist_finish()` forces the matching finished write for any run
     that was slow or overdue — so an escalated `is_running=True` is always
     cleared, and healthy fast runs still write nothing. The in-process
     watchdog (ERROR log + `scheduler_task_stuck` event) was already unaffected.
4. **Log demotion** — the three per-run lines in
   `backend/scheduler/runner.py` ("scheduled for", "starting",
   "completed in") drop from INFO to DEBUG. Failure/slow logging unchanged.

## Acceptance Criteria

- [ ] **AC-1**: Given a warmed Zigbee2MQTT settings cache, processing N
  inbound Z2M messages issues zero `AlarmSettingsProfile` /
  `AlarmSettingsEntry` queries; after `settings_profile_changed` fires, the
  next message observes the updated settings.
- [ ] **AC-2**: Same as AC-1 for Frigate inbound messages.
- [ ] **AC-3**: Given no `NotificationDelivery` rows in `PENDING`/`SENDING`,
  a `notifications_send_pending` tick issues exactly one query and returns
  0; given a due `PENDING` row, delivery proceeds exactly as before
  (existing tests pass unmodified).
- [ ] **AC-4**: Given no `SCHEDULED` `PendingAction` rows, a
  `fire_due_pending_actions` tick issues exactly one query; given due or
  stale rows, firing and stale-cancelling behave exactly as before
  (existing tests pass unmodified).
- [ ] **AC-5**: For a sub-minute-interval task running healthily,
  `scheduler_taskhealth` receives at most one scheduling/started/finished
  persist per ~60s window; a failing run persists failure state
  immediately.
- [ ] **AC-6**: A healthy no-op run of any fast task emits zero INFO-level
  log lines from the scheduler runner (the three per-run lines are DEBUG).
- [ ] **AC-7**: Full backend suite passes — timer transitions,
  pending-action firing, notification retries, and rule processing
  unchanged.
- [ ] **AC-8**: A settings-profile update or activation (which fires
  `settings_profile_changed` on commit) is reflected in ingest-handler
  behavior without process restart.

## Consequences

### Positive

- Settings-table reads drop from ~1.9/s (and growing with device count) to
  ~0 at steady state.
- Idle query floor drops from ~3.4/s to ~1.5/s of single cheap guards.
- `scheduler_taskhealth` write load drops from ~3–6/s to ~0.1/s.
- Idle log volume drops from ~7 lines/s to ~0, making real events visible.

### Negative

- Scheduler status UI data may be up to ~60s stale for fast healthy tasks
  (~2 windows for intervals just under 60s). Sub-minute tasks will rarely
  render as `running`, since their `started` write is usually throttled away —
  their runs are milliseconds, so the badge was near-unobservable regardless.
  Overdue runs escalate, so `stuck` stays accurate.
- Ingest settings caches add one more place where settings changes depend
  on the `settings_profile_changed` signal firing (precedented; direct DB
  edits via shell or Django admin already bypass the existing snapshot cache
  the same way, and now also change ingest behavior until restart).
- Tests that write settings rows directly bypass the signal, so
  `alarm/tests/settings_test_utils.set_profile_setting` clears the snapshots on
  write. Without that, a snapshot warmed by one test leaks into the next and
  makes assertions depend on execution order.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A settings write path that doesn't fire `settings_profile_changed` leaves ingest caches stale | Low | Medium | Sender coverage verified (use cases + all five integration views, all via `on_commit`); document the signal contract in the cache docstring |
| Multi-replica deployment: another replica's settings write doesn't invalidate this replica's cache | Low | Medium | Same limitation as the existing `_settings_snapshot`; shipped deployment is single-process; note in docs |
| Telemetry throttle hides a fast task that silently stops running | Low | Low | Failures always persist; watchdog thread-liveness checks are in-process and unaffected; throttle window is only ~60s |
| Throttled `started` write hides a *hung* sub-minute task from the DB-derived `running`/`stuck` status in `scheduler/views.py` (both gated on `is_running`) | Medium | Medium | Supervisor calls `persist_running_now()` once a run passes `max_runtime_seconds`; `should_persist_finish()` forces the paired finish write so the row never sticks at `is_running=True`; in-process ERROR log + `scheduler_task_stuck` event were never gated on the throttle |
| Module snapshot warmed by one test leaks into another, making assertions order-dependent | Medium | Low | `set_profile_setting` clears the snapshots on write; tests that write rows directly reset them in `setUp`/`tearDown` |
| `exists()` guard adds a third query when work IS pending | High | Negligible | One extra LIMIT-1 scan on a tiny table only on active ticks |

## Implementation Plan

- [ ] Phase 1: Z2M + Frigate ingest settings caches with signal
  invalidation (AC-1, AC-2, AC-8) — tests first.
- [ ] Phase 2: `exists()` guards in `notifications_send_pending` and
  `fire_due_pending_actions` (AC-3, AC-4) — tests first.
- [ ] Phase 3: telemetry write throttle in `scheduler/telemetry.py`
  (AC-5).
- [ ] Phase 4: runner log demotion (AC-6); `ruff` + full backend suite
  (AC-7); update the ADR index.

## Related ADRs

- [ADR-0102](./0102-change-only-entity-sync-writes.md) — removed the
  dominant write amplification; this ADR is the remaining idle floor.
- [ADR-0091](./0091-rule-action-entry-delay.md) — introduced the
  pending-actions queue whose tick gains a guard.
- [ADR-0093](./0093-scheduler-instance-id-stable-default.md) — scheduler
  telemetry/instance conventions the throttle builds on.
- [ADR-0079](./0079-ui-config-with-encrypted-credentials.md) — the
  DB-backed settings this caches.

## References

- [Issue #80 — scheduler polling tasks issue ~2.2M queries/week](https://github.com/latchpoint/latchpoint/issues/80)
- `backend/alarm/system_status.py` — the `_settings_snapshot` +
  `settings_profile_changed` pattern being copied.
