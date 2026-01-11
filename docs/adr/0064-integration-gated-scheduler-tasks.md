# ADR 0064: Integration-Gated Scheduler Tasks

## Status
Partially Implemented

## Context
The app uses an in-process, thread-based scheduler (ADR 0024). Today, some scheduled tasks run on a fixed cadence even when their associated integration is not enabled/configured (e.g. Home Assistant status checks or entity sync loops).

Concrete examples in the current codebase:
- `alarm.tasks.check_home_assistant` runs every ~30s and calls into system status recomputation with `include_home_assistant=True`.
- `alarm.tasks.sync_entity_states` runs every 5 minutes and attempts to sync Home Assistant entity states.
- `integrations_frigate.tasks.cleanup_frigate_detections` runs hourly and exits early when Frigate is disabled.

This has a few downsides:
- Wasted CPU/wakeups (especially for frequent tasks) and extra thread overhead.
- Unnecessary log noise (“not configured / unavailable” messages).
- Risk of accidental external IO (e.g. connectivity checks) when a user has explicitly not enabled an integration.
- Harder-to-reason-about behavior: “task exists” is not the same as “feature is active”.

We want “don’t start tasks unless they are needed” semantics, while still supporting enabling an integration at runtime without requiring a process restart.

## Decision
Add first-class **runtime gating** to scheduler tasks so that integration-specific tasks:
1) do not start (no long-lived task loop/thread) unless their integration is active, and
2) automatically start when the integration becomes active, and
3) automatically stop when the integration becomes inactive.

### Identified tasks (apply gating)
- Home Assistant:
  - `check_home_assistant`
  - `sync_entity_states`
- Frigate:
  - `cleanup_frigate_detections`

### Proposed mechanism
Extend the scheduler registry and runner with a dynamic enablement concept:
- Task registration supports an `enabled_when` predicate (`Callable[[], bool]`) in addition to static `enabled: bool`.
- The scheduler watchdog evaluates `enabled_when` periodically:
  - If `enabled_when` is `True` and there is no thread for the task, start it.
  - If `enabled_when` becomes `False`, the task loop exits gracefully (and the watchdog does not restart it until enabled again).
- When disabled, the scheduler still surfaces task metadata (so UI/status remains consistent), but does not run or schedule executions.

### Integration gating rules (initial)
- Home Assistant periodic tasks (e.g. “check reachability”, “entity sync”) are gated by “Home Assistant enabled and minimally configured” in the active settings profile.
- Other integration tasks (MQTT, Z-Wave JS, Zigbee2MQTT, Frigate) follow the same pattern: task threads exist only when the integration is enabled.

This is intended to complement (not replace) existing in-task “early return when disabled/unavailable” guards; those remain as a safety net.

## Alternatives Considered
- Keep existing behavior and ensure tasks are cheap no-ops when disabled.
  - Simple, but still pays the thread/wakeup cost and can still create noisy logs.
- Conditionally import/register tasks only when an integration is enabled (e.g. in `AppConfig.ready()`).
  - Avoids threads, but enabling/disabling at runtime would require a process restart to take effect.
- Replace the scheduler with an external system (Celery/RQ/cron).
  - Operationally heavier; contrary to the “in-process” direction of ADR 0024.

## Consequences
- Scheduler becomes more complex (needs periodic evaluation of enablement predicates and a “stop” path).
- The “task list” becomes a mix of “registered tasks” and “currently active tasks”, so status APIs/UI should surface both “registered” and “running/enabled” state explicitly.
- Enablement predicates must be efficient and side-effect free (no network IO; minimal DB reads).

## Todos
### Phased rollout plan
- Phase 1 (scheduler support):
  - Extend `backend/scheduler/registry.py` to support `enabled_when` (or `enabled: bool | Callable[[], bool]`) with a clear API.
  - Update `backend/scheduler/runner.py` watchdog + task loop to start/stop tasks based on dynamic enablement.
  - Add regression tests in `backend/scheduler/tests/` for:
    - tasks not started when `enabled_when=False`
    - tasks started when `enabled_when` flips to `True`
    - tasks stop when `enabled_when` flips to `False`
    - status reporting remains stable for disabled tasks
- Phase 2 (Home Assistant gating):
  - Add a shared helper for “Home Assistant is active” checks (active profile setting lookup) to avoid duplicated DB logic across tasks.
  - Gate `check_home_assistant` and `sync_entity_states` behind the Home Assistant predicate.
- Phase 3 (other integrations):
  - Add a shared helper for “Frigate is active” checks and gate `cleanup_frigate_detections`.
  - Audit any newly-added integration tasks and default them to gated unless there’s a clear reason not to.

## Implementation Notes
- Implemented dynamic gating via `enabled_when` in the scheduler registry/runner, and applied it to:
  - Home Assistant: `check_home_assistant`, `sync_entity_states`
  - Frigate: `cleanup_frigate_detections`
- Scheduler status API/UI surfaces gated tasks as disabled, with an explicit reason (e.g. gated vs disabled).
- Remaining work is to apply the same pattern to any future scheduled tasks for other integrations (MQTT/Z-Wave JS/Zigbee2MQTT) as they are added.
