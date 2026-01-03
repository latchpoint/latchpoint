# ADR-0042: Integration Status Monitoring

## Status
Implemented

## Related
- **ADR-0024**: In-Process Task Scheduler (provides scheduler framework)
- **ADR-0028**: Deprecated - superseded by this ADR
- **ADR-0030**: Deprecated - superseded by this ADR

## Context
The alarm system integrates with multiple external services:
- **Home Assistant**: Primary home automation platform
- **MQTT**: Message broker for real-time events
- **Z-Wave JS**: Z-Wave device control
- **Zigbee2MQTT**: Zigbee device integration
- **Frigate**: NVR/camera integration

### Requirements
1. **Real-time UI updates**: Dashboard shows integration status with ~2 second latency
2. **Historical record**: Outages logged for debugging and correlation with alarm events
3. **Alerting foundation**: Significant outages create events that can trigger notifications
4. **Single source of truth**: No duplicate polling or parallel systems

### Previous State (removed)
`backend/alarm/system_status.py` used custom daemon threads for periodic status updates, which duplicated scheduler infrastructure (ADR-0024) and had no watchdog.

## Decision
Migrate status monitoring to scheduler jobs with signal-based persistence.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                 Integration Status Monitoring                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Scheduler (ADR-0024)                    │   │
│  │                                                          │   │
│  │  ┌────────────────────┐    ┌────────────────────┐        │   │
│  │  │ broadcast_system_   │    │ check_home_        │        │   │
│  │  │ status              │    │ assistant          │        │   │
│  │  │ Every 2s           │    │ Every 30s          │        │   │
│  │  └─────────┬──────────┘    └─────────┬──────────┘        │   │
│  │            │                         │                   │   │
│  │            └────────────┬────────────┘                   │   │
│  │                         ▼                                │   │
│  │            ┌──────────────────────────────────┐          │   │
│  │            │ recompute_and_broadcast_system_   │          │   │
│  │            │ status (detects changes + emits   │          │   │
│  │            │ observation signals)              │          │   │
│  │            └────────────┬──────────────────────┘          │   │
│  └─────────────────────────┼────────────────────────────────┘   │
│                            │                                    │
│              ┌─────────────┴─────────────┐                      │
│              ▼                           ▼                      │
│  ┌────────────────────┐      ┌────────────────────┐             │
│  │ WebSocket Broadcast │      │ integration_status │             │
│  │ (real-time UI)      │      │ _changed signal    │             │
│  └────────────────────┘      └─────────┬──────────┘             │
│                                        │                        │
│                                        ▼                        │
│                              ┌────────────────────┐             │
│                              │ Signal Receiver    │             │
│                              │ (persists events)  │             │
│                              └────────────────────┘             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation

#### 1. New Signal

```python
# backend/alarm/signals.py
from django.dispatch import Signal

# Sent when an integration transitions online/offline.
# Args: integration (str), is_healthy (bool), previous_healthy (bool | None)
integration_status_changed = Signal()

# Sent on each scheduler tick (even if status didn't change), so we can
# implement "offline for >= N seconds" logic without needing a second poller.
# Args: integration (str), is_healthy (bool), checked_at (datetime)
integration_status_observed = Signal()
```

#### 2. Scheduler Tasks

```python
# backend/alarm/tasks.py
from scheduler import register, Every

@register("broadcast_system_status", schedule=Every(seconds=2))
def broadcast_system_status() -> None:
    """Broadcast integration status to WebSocket clients (local integrations)."""
    from alarm.system_status import recompute_and_broadcast_system_status
    recompute_and_broadcast_system_status(include_home_assistant=False)


@register("check_home_assistant", schedule=Every(seconds=30, jitter=5))
def check_home_assistant() -> None:
    """Check Home Assistant status and broadcast if changed."""
    from alarm.system_status import recompute_and_broadcast_system_status
    recompute_and_broadcast_system_status(include_home_assistant=True)
```

#### 3. Refactored system_status.py

```python
# backend/alarm/system_status.py
"""Integration status monitoring with signal-based state change notification."""

from __future__ import annotations

import logging
import threading
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from alarm.signals import integration_status_changed, integration_status_observed

logger = logging.getLogger(__name__)

_status_lock = threading.Lock()
_last_system_status_payload: dict[str, Any] | None = None

# Track per-integration health for transition detection
_last_health: dict[str, bool] = {}


def _extract_health(payload: dict[str, Any] | None, name: str) -> bool | None:
    """Extract health status for an integration from payload."""
    if payload is None:
        return None

    if name == "mqtt":
        return payload.get("mqtt", {}).get("connected", False)
    elif name == "zwavejs":
        return payload.get("zwavejs", {}).get("connected", False)
    elif name == "zigbee2mqtt":
        return payload.get("zigbee2mqtt", {}).get("connected", False)
    elif name == "frigate":
        return payload.get("frigate", {}).get("available", False)
    elif name == "home_assistant":
        return payload.get("home_assistant", {}).get("reachable", False)
    return None


def recompute_and_broadcast_system_status(*, include_home_assistant: bool) -> None:
    """
    Recompute system status, broadcast changes, and emit signals.

    Websocket broadcasts only happen when the payload changes, but observation
    signals still fire on each run so outage-threshold logic can work while an
    integration remains offline.
    """
    payload = _compute_system_status_payload(include_home_assistant=include_home_assistant)

    integrations = ["mqtt", "zwavejs", "zigbee2mqtt", "frigate", "home_assistant"]
    checked_at = timezone.now()

    # Detect state transitions and emit signals
    for name in integrations:
        is_healthy = _extract_health(payload, name)
        was_healthy = _last_health.get(name)

        if is_healthy is not None:
            integration_status_observed.send(
                sender=None,
                integration=name,
                is_healthy=is_healthy,
                checked_at=checked_at,
            )

        if is_healthy is not None and is_healthy != was_healthy:
            _last_health[name] = is_healthy
            integration_status_changed.send(
                sender=None,
                integration=name,
                is_healthy=is_healthy,
                previous_healthy=was_healthy,
            )

    with _status_lock:
        global _last_system_status_payload
        old_payload = _last_system_status_payload
        if old_payload == payload:
            return
        _last_system_status_payload = payload

    # Broadcast to WebSocket clients
    _channel_broadcast(message=_build_system_status_message(payload=payload))


# Remove: start_system_status_threads(), _should_start_threads(),
#         _local_loop(), _ha_loop(), _threads_started
# Keep: _compute_system_status_payload(), _channel_broadcast(),
#       _build_system_status_message(), get_current_system_status_message()
```

#### 4. Signal Receiver for Persistence

```python
# backend/alarm/receivers.py
from datetime import timedelta
import logging

from django.dispatch import receiver
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType
from alarm.signals import integration_status_changed, integration_status_observed

logger = logging.getLogger(__name__)

_offline_since: dict[str, timezone.datetime] = {}
_offline_event_emitted: set[str] = set()
_OUTAGE_THRESHOLD_SECONDS = 60


@receiver(integration_status_changed)
def log_integration_transition(sender, integration, is_healthy, previous_healthy, **kwargs):
    """Persist significant integration state transitions as AlarmEvents."""
    now = timezone.now()

    if previous_healthy is None:
        # First observation after startup - just record if offline
        if not is_healthy:
            _offline_since[integration] = now
        return

    if previous_healthy and not is_healthy:
        # Went offline
        _offline_since[integration] = now
        _offline_event_emitted.discard(integration)
        logger.warning("Integration %s went offline", integration)

    elif not previous_healthy and is_healthy:
        # Came back online
        offline_duration = (now - _offline_since.get(integration, now)).total_seconds()
        logger.info("Integration %s back online after %.0fs", integration, offline_duration)

        if offline_duration >= _OUTAGE_THRESHOLD_SECONDS:
            AlarmEvent.objects.create(
                event_type=AlarmEventType.INTEGRATION_RECOVERED,
                timestamp=now,
                metadata={
                    "integration": integration,
                    "offline_duration_seconds": offline_duration,
                },
            )
        _offline_since.pop(integration, None)
        _offline_event_emitted.discard(integration)


@receiver(integration_status_observed)
def log_prolonged_outage(sender, integration, is_healthy, checked_at, **kwargs):
    """Create outage event once an integration is offline for the threshold duration."""
    if is_healthy:
        return

    offline_start = _offline_since.get(integration)
    if not offline_start:
        return

    offline_duration = (checked_at - offline_start).total_seconds()
    if offline_duration < _OUTAGE_THRESHOLD_SECONDS:
        return

    if integration in _offline_event_emitted:
        return

    # Avoid duplicate events within 5 minutes (belt-and-suspenders)
    now = timezone.now()
    recent_event = AlarmEvent.objects.filter(
        event_type=AlarmEventType.INTEGRATION_OFFLINE,
        timestamp__gte=now - timedelta(minutes=5),
        metadata__integration=integration,
    ).exists()

    if not recent_event:
        logger.error("Integration %s offline for %.0fs", integration, offline_duration)
        AlarmEvent.objects.create(
            event_type=AlarmEventType.INTEGRATION_OFFLINE,
            timestamp=now,
            metadata={
                "integration": integration,
                "offline_duration_seconds": offline_duration,
            },
        )
        _offline_event_emitted.add(integration)
```

#### 5. New Event Types

```python
# backend/alarm/models.py
class AlarmEventType(models.TextChoices):
    # ... existing types ...
    INTEGRATION_OFFLINE = "integration_offline", "Integration offline"
    INTEGRATION_RECOVERED = "integration_recovered", "Integration recovered"
```

## Alternatives Considered

### Keep custom threads alongside scheduler
- **Pros**: No migration effort
- **Cons**: Duplicate infrastructure, no watchdog, two patterns for same thing
- **Verdict**: Not worth the complexity

### Single polling job at 2s for everything
- **Pros**: Simpler
- **Cons**: Home Assistant check is a network call; 2s is too aggressive
- **Verdict**: Keep separate intervals (2s local, 30s HA)

## Consequences

### Positive
- Single pattern for all periodic work (scheduler)
- Watchdog auto-restarts dead tasks
- Management commands for debugging (`./manage.py run_task broadcast_system_status`)
- Signal-based persistence - no duplicate polling
- Less custom code to maintain

### Negative
- Migration effort to remove thread infrastructure
- Slightly different timing characteristics (scheduler jitter)
- Receiver state is in-memory (resets on restart) unless extended to persist outages in DB

### Mitigations
- Scheduler jitter is minimal at 2s intervals
- Can run old and new in parallel during migration for verification

## Migration Steps

1. Add `integration_status_changed` signal
2. Add `integration_status_observed` signal
3. Add scheduler tasks (`broadcast_system_status`, `check_home_assistant`)
4. Refactor `recompute_and_broadcast_system_status` to emit signals
5. Add signal receivers for persistence
6. Add new `AlarmEventType` values
7. Remove thread infrastructure from `system_status.py`:
   - `start_system_status_threads()`
   - `_should_start_threads()`
   - `_local_loop()`
   - `_ha_loop()`
   - `_threads_started`
8. Remove `start_system_status_threads()` call from `AlarmConfig.ready()`
9. Add tests

## Todos
- [ ] Add `integration_status_changed` signal to `alarm/signals.py`
- [ ] Add `integration_status_observed` signal to `alarm/signals.py`
- [ ] Add `INTEGRATION_OFFLINE` and `INTEGRATION_RECOVERED` to `AlarmEventType`
- [ ] Add scheduler tasks to `alarm/tasks.py`
- [ ] Refactor `system_status.py` to emit signals
- [ ] Add signal receivers to `alarm/receivers.py`
- [ ] Remove thread infrastructure from `system_status.py`
- [ ] Update `AlarmConfig.ready()` to not start threads
- [ ] Add tests for signal emission and receivers
- [ ] Update AGENTS.md with new architecture
