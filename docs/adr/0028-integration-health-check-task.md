# ADR-0028: Integration Health Check Task

## Status
Deprecated - superseded by ADR-0042

## Related
- **ADR-0042**: Integration Status Monitoring (consolidates this ADR with ADR-0030)

## Context
The alarm system integrates with multiple external services:
- **Home Assistant**: Primary home automation platform
- **MQTT**: Message broker for real-time events
- **Z-Wave JS**: Z-Wave device control
- **Zigbee2MQTT**: Zigbee device integration
- **Frigate**: NVR/camera integration

Currently, integration status is:
- Computed on-demand in `system_status.py` every 2-30 seconds
- Broadcast to WebSocket clients for real-time UI updates
- Not persisted or logged for historical analysis

### Problem
When an integration goes offline:
1. Users only see status if actively viewing the UI
2. No historical record of outages for debugging
3. No alerting mechanism for prolonged outages
4. No way to correlate alarm events with integration availability

### Requirements
1. Detect when integrations transition from online to offline (and vice versa)
2. Log state transitions for debugging
3. Create `AlarmEvent` records for significant outages
4. Support future alerting/notification hooks
5. Avoid duplicate events for flapping connections

## Decision
Add a scheduled task `check_integration_health` that monitors integration status and logs transitions.

### Implementation

This task uses the shared health check module (see ADR-0030) to avoid duplicating
logic already present in `system_status.py`.

```python
# backend/alarm/tasks.py
from scheduler import register, Every

# Track last known states to detect transitions
_last_integration_states: dict[str, bool] = {}
_offline_since: dict[str, datetime] = {}
_OUTAGE_THRESHOLD_SECONDS = 60  # Only log event after 60s offline

@register("check_integration_health", schedule=Every(seconds=30, jitter=5))
def check_integration_health() -> dict:
    """
    Check integration health and log state transitions.

    Returns dict with current status of each integration.
    """
    from alarm.health import (
        check_home_assistant,
        check_mqtt,
        check_zwavejs,
        check_zigbee2mqtt,
        check_frigate,
    )

    now = timezone.now()
    results = {}

    integrations = [
        ("home_assistant", check_home_assistant),
        ("mqtt", check_mqtt),
        ("zwavejs", check_zwavejs),
        ("zigbee2mqtt", check_zigbee2mqtt),
        ("frigate", check_frigate),
    ]

    for name, check_fn in integrations:
        try:
            is_healthy = check_fn()
        except Exception as e:
            logger.warning("Health check failed for %s: %s", name, e)
            is_healthy = False

        results[name] = is_healthy
        _handle_state_transition(name, is_healthy, now)

    return results


def _handle_state_transition(name: str, is_healthy: bool, now: datetime) -> None:
    """Handle state transitions and log/record significant events."""
    was_healthy = _last_integration_states.get(name)
    _last_integration_states[name] = is_healthy

    if was_healthy is None:
        # First check, just record state
        if not is_healthy:
            _offline_since[name] = now
        return

    if was_healthy and not is_healthy:
        # Went offline
        _offline_since[name] = now
        logger.warning("Integration %s went offline", name)

    elif not was_healthy and is_healthy:
        # Came back online
        offline_duration = (now - _offline_since.get(name, now)).total_seconds()
        logger.info("Integration %s came back online after %.0fs", name, offline_duration)

        if offline_duration >= _OUTAGE_THRESHOLD_SECONDS:
            # Record recovery event
            AlarmEvent.objects.create(
                event_type=AlarmEventType.INTEGRATION_RECOVERED,
                source=name,
                metadata={
                    "integration": name,
                    "offline_duration_seconds": offline_duration,
                },
            )
        _offline_since.pop(name, None)

    elif not is_healthy:
        # Still offline - check if we should create outage event
        offline_duration = (now - _offline_since.get(name, now)).total_seconds()
        if offline_duration >= _OUTAGE_THRESHOLD_SECONDS:
            # Check if we already logged this outage
            recent_event = AlarmEvent.objects.filter(
                event_type=AlarmEventType.INTEGRATION_OFFLINE,
                source=name,
                timestamp__gte=now - timedelta(minutes=5),
            ).exists()

            if not recent_event:
                logger.error("Integration %s offline for %.0fs", name, offline_duration)
                AlarmEvent.objects.create(
                    event_type=AlarmEventType.INTEGRATION_OFFLINE,
                    source=name,
                    metadata={"integration": name},
                )
```

### Event Types
Add to `AlarmEventType` choices:
```python
INTEGRATION_OFFLINE = "integration_offline"
INTEGRATION_RECOVERED = "integration_recovered"
```

### Schedule
- **Interval**: Every 30 seconds
- **Rationale**: Fast enough to detect outages quickly, not so fast as to spam logs

### Debouncing
- Wait 60 seconds before recording an outage (avoids flapping)
- Don't create duplicate outage events within 5 minutes
- Record recovery with offline duration for analysis

## Alternatives Considered

### Use existing system_status threads
- **Pros**: Already running, no new task needed
- **Cons**: Not using scheduler; no event persistence; tightly coupled to WebSocket
- **Verdict**: Keep system_status for real-time UI; add task for persistence/alerting

### Webhook/push notifications on outage
- **Pros**: Immediate alerts
- **Cons**: Requires notification infrastructure; out of scope for health check
- **Verdict**: Health check creates events; separate notification system can watch events

## Consequences

### Positive
- Historical record of integration outages
- Correlated timeline with alarm events
- Foundation for alerting system
- Visibility into integration reliability

### Negative
- Additional polling (every 30s)
- New event types to handle in UI
- In-memory state tracking (resets on restart)

### Mitigations
- Minimal overhead (simple status checks)
- Event types can be filtered/hidden in UI if needed
- State tracking is best-effort; first check after restart is clean slate

## Todos
- [ ] Implement shared health check module `alarm/health.py` (ADR-0030 dependency)
- [ ] Add `INTEGRATION_OFFLINE` and `INTEGRATION_RECOVERED` to `AlarmEventType`
- [ ] Implement `check_integration_health` task in `alarm/tasks.py`
- [ ] Add tests for state transition logic
- [ ] Consider adding to UI event timeline with appropriate styling
