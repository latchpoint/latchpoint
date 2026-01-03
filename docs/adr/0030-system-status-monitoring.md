# ADR-0030: System Status Monitoring Architecture

## Status
Deprecated - superseded by ADR-0042

## Related
- **ADR-0042**: Integration Status Monitoring (consolidates this ADR with ADR-0028)

## Context
The alarm system needs real-time visibility into integration status for:
- UI dashboard showing connection states
- WebSocket broadcasts when status changes
- Debugging connectivity issues

### Current Implementation
`backend/alarm/system_status.py` implements status monitoring via dedicated threads:

```python
# Local status thread (every 2 seconds)
def _local_loop():
    while True:
        recompute_and_broadcast_system_status(include_home_assistant=False)
        time.sleep(2)

# Home Assistant status thread (every 30 seconds)
def _ha_loop():
    while True:
        if ha_enabled:
            recompute_and_broadcast_system_status(include_home_assistant=True)
        time.sleep(30)
```

These threads:
- Run independently of the scheduler (ADR-0024)
- Broadcast changes to WebSocket clients
- Cache last-known status for API responses
- Use their own `_should_start_threads()` logic

### Questions
1. Should this migrate to the scheduler framework for consistency?
2. Are separate threads still appropriate for real-time requirements?
3. How does this relate to the new health check task (ADR-0028)?

## Decision
**Keep current implementation** with minor enhancements.

### Rationale
The existing `system_status.py` threads are purpose-built for real-time status:

| Requirement | Scheduler Tasks | Status Threads |
|-------------|-----------------|----------------|
| Sub-second latency | ❌ Min 1s interval | ✅ Designed for it |
| WebSocket integration | Requires extra wiring | ✅ Built-in |
| Change detection | Each task is stateless | ✅ Diff-based broadcast |
| Restart on crash | ✅ Watchdog | ❌ No watchdog |

### Relationship to Other Tasks

```
┌─────────────────────────────────────────────────────────────────┐
│                    Integration Monitoring                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────┐     ┌──────────────────────┐         │
│  │  system_status.py    │     │  Scheduler Tasks     │         │
│  │  (Real-time)         │     │  (Periodic)          │         │
│  ├──────────────────────┤     ├──────────────────────┤         │
│  │ • 2-30s intervals    │     │ • 30s-5m intervals   │         │
│  │ • WebSocket broadcast│     │ • Persistent events  │         │
│  │ • UI status display  │     │ • Alerting/logging   │         │
│  │ • In-memory only     │     │ • AlarmEvent records │         │
│  └──────────────────────┘     └──────────────────────┘         │
│           │                            │                        │
│           ▼                            ▼                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                 Integration Managers                      │  │
│  │  (mqtt_connection_manager, zwavejs_connection_manager)   │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

- **system_status.py**: Real-time UI updates, ephemeral
- **check_integration_health (ADR-0028)**: Persistent event logging, alerting

### Proposed Enhancements

1. **Add watchdog** to status threads (follow ADR-0024 scheduler pattern):
   - The scheduler framework already implements a robust watchdog in `backend/scheduler/runner.py`
   - Apply the same pattern: check thread liveness every 60s, restart if dead
   - Lower priority since system_status threads are simple infinite loops

2. **Share health check logic** with ADR-0028:
```python
# alarm/health.py (shared module)
def check_home_assistant() -> bool: ...
def check_mqtt() -> bool: ...
def check_zwavejs() -> bool: ...
```

3. **Document the split** in AGENTS.md

## Alternatives Considered

### Migrate to scheduler
- **Pros**: Single pattern for all periodic work
- **Cons**: Scheduler isn't designed for 2-second intervals; adds complexity for WebSocket integration
- **Verdict**: Keep separate for now; revisit if scheduler gains sub-second support

### Merge with health check task
- **Pros**: Single source of truth for integration status
- **Cons**: Different requirements (real-time vs persistent)
- **Verdict**: Keep separate but share underlying check functions

## Consequences

### Positive
- Real-time status works as expected
- Clear separation of concerns (real-time vs audit)
- No breaking changes to existing behavior

### Negative
- Two parallel systems for integration monitoring
- Slightly more complex mental model

### Mitigations
- Document the architecture clearly
- Share health check implementation where possible
- Consider future unification if patterns converge

## Todos
- [ ] Extract health check functions to shared `alarm/health.py` module
- [ ] Document architecture in AGENTS.md
- [ ] Consider adding `get_system_status()` to scheduler's `get_scheduler_status()` for unified health endpoint
- [ ] (Optional) Add watchdog to system_status threads following ADR-0024 pattern
