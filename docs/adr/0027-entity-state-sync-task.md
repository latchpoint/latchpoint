# ADR-0027: Entity State Sync Task

## Status
Accepted

## Context
The alarm system maintains an entity registry (`Entity` model) that stores sensor/device states imported from Home Assistant. Entity states are updated via:

1. **Manual sync**: User triggers `POST /api/alarm/entities/sync/`
2. **Real-time updates**: State changes pushed via WebSocket/MQTT subscriptions

However, there are scenarios where entity states can become stale:
- Network blips causing missed state change events
- Home Assistant restarts where event stream is interrupted
- Long periods of inactivity where no state changes occur
- Reconnection scenarios where historical states aren't replayed

### Current State
- `Entity.last_state` may not reflect current reality after connectivity issues
- `Entity.last_seen` can indicate staleness but isn't actively monitored
- No automatic mechanism to detect and correct stale states

### Requirements
1. Periodically refresh entity states from Home Assistant
2. Only sync when Home Assistant integration is enabled and reachable
3. Avoid overwhelming Home Assistant with frequent requests
4. Log discrepancies between cached and actual states
5. Update `last_seen` timestamp on successful sync

## Decision
Add a scheduled task `sync_entity_states` that refreshes entity states from Home Assistant, with a configurable sync interval.

### Configuration
Add to `settings_registry.py`:
```python
SettingDefinition(
    key="entity_sync.interval_seconds",
    name="Entity sync interval (seconds)",
    value_type=SystemConfigValueType.INTEGER,
    default=300,
    description="How often to sync entity states from Home Assistant (0 to disable).",
),
```

### Implementation

```python
# backend/alarm/tasks.py
import logging
from datetime import timedelta

from django.utils import timezone

from scheduler import register, Every

logger = logging.getLogger(__name__)


def _get_entity_sync_interval() -> int:
    """Return configured entity sync interval in seconds."""
    from alarm.models import SystemConfig
    from alarm.settings_registry import SYSTEM_CONFIG_SETTINGS_BY_KEY

    setting = SYSTEM_CONFIG_SETTINGS_BY_KEY["entity_sync.interval_seconds"]
    return SystemConfig.get_value(setting.key, setting.default)


@register("sync_entity_states", schedule=Every(seconds=300, jitter=30))
def sync_entity_states() -> dict:
    """
    Refresh entity states from Home Assistant.

    Returns dict with counts: {"synced": N, "updated": N, "errors": N}
    """
    from alarm.gateways.home_assistant import default_home_assistant_gateway
    from alarm.models import Entity

    interval = _get_entity_sync_interval()
    if interval <= 0:
        logger.debug("Entity sync disabled (interval=%d)", interval)
        return {"synced": 0, "updated": 0, "errors": 0, "disabled": True}

    try:
        default_home_assistant_gateway.ensure_available()
    except Exception as e:
        logger.debug("Skipping entity sync: Home Assistant unavailable (%s)", e)
        return {"synced": 0, "updated": 0, "errors": 0, "skipped": True}

    try:
        ha_entities = default_home_assistant_gateway.list_entities()
    except Exception as e:
        logger.warning("Entity sync failed to fetch from Home Assistant: %s", e)
        return {"synced": 0, "updated": 0, "errors": 1}

    ha_states = {e["entity_id"]: e for e in ha_entities}
    now = timezone.now()
    updated = 0
    synced = 0

    for entity in Entity.objects.filter(source="home_assistant"):
        ha_data = ha_states.get(entity.entity_id)
        if not ha_data:
            continue

        new_state = ha_data.get("state")
        update_fields = ["last_seen"]

        if entity.last_state != new_state:
            logger.info(
                "Entity %s state changed: %s -> %s (detected via sync)",
                entity.entity_id,
                entity.last_state,
                new_state,
            )
            entity.last_state = new_state
            entity.last_changed = now
            update_fields.extend(["last_state", "last_changed"])
            updated += 1

        entity.last_seen = now
        entity.save(update_fields=update_fields)
        synced += 1

    if updated > 0:
        logger.info("Entity sync: updated %d entities with changed states", updated)

    return {"synced": synced, "updated": updated, "errors": 0}
```

### Schedule
- **Interval**: Default 5 minutes (300 seconds), configurable via UI
- **Jitter**: ±30 seconds to avoid thundering herd with other tasks
- **Disable**: Set interval to 0 to disable automatic sync
- **Rationale**: Balances freshness with not overloading Home Assistant

### Behavior
1. Skip silently if Home Assistant is not configured or unreachable
2. Fetch current states from Home Assistant API
3. Compare with stored states in entity registry
4. Update changed states and log discrepancies
5. Always update `last_seen` for successfully synced entities

## Alternatives Considered

### WebSocket subscription only
- **Pros**: Real-time, no polling overhead
- **Cons**: Can miss events during disconnections; no catch-up mechanism
- **Verdict**: Keep WebSocket as primary, use sync as backup

### More frequent polling (every 30s)
- **Pros**: Faster detection of stale states
- **Cons**: Higher load on Home Assistant; most states don't change frequently
- **Verdict**: 5 minutes is sufficient for catch-up purposes

### On-demand sync only
- **Pros**: User controls when sync happens
- **Cons**: Users may not notice stale states; manual intervention required
- **Verdict**: Automatic sync provides safety net

## Consequences

### Positive
- Self-healing for missed state change events
- Consistent entity states after connectivity issues
- Visibility into sync health via logs
- `last_seen` provides staleness indicator

### Negative
- Additional API calls to Home Assistant (every 5 min)
- Slight delay (up to 5 min) before stale states are corrected
- Database writes on every sync (can optimize with dirty-checking)

### Mitigations
- Jitter prevents synchronized load spikes
- Only syncs HA entities, not all entities
- Bulk fetch + selective updates minimizes DB operations

## Todos
- [x] Add `entity_sync.interval_seconds` to `settings_registry.py`
- [x] Implement `sync_entity_states` task in `alarm/tasks.py`
- [x] Add tests for sync task (mock HA gateway)
- [x] Emit WebSocket `entity_sync` event on state changes detected via sync
