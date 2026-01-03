# ADR-0026: Rule Action Log Cleanup Task

## Status
Accepted

## Context
The `RuleActionLog` model stores a record for every rule execution, including:
- Which rule fired and when
- The triggering entity
- Actions executed and their results
- Alarm state before/after
- Error traces for debugging

Over time, this table can grow unbounded, consuming database storage and potentially impacting query performance. Similar to event cleanup (ADR-0023), we need automated pruning of old rule execution logs.

### Current State
- `RuleActionLog` entries accumulate indefinitely
- No cleanup mechanism exists
- Table includes detailed JSON fields (`actions`, `result`, `trace`) that can be large

### Requirements
1. Delete `RuleActionLog` entries older than a configurable retention period
2. Default retention should balance debugging needs with storage (e.g., 14 days)
3. Run automatically via the scheduler (ADR-0024)
4. Configurable via `SystemConfig` like event retention
5. Idempotent and safe to run multiple times

## Decision
Add a scheduled task `cleanup_rule_action_logs` that deletes old rule execution logs.

### Implementation

```python
# backend/alarm/tasks.py
from scheduler import register, DailyAt

@register("cleanup_rule_action_logs", schedule=DailyAt(hour=3, minute=30))
def cleanup_rule_action_logs() -> int:
    """Delete RuleActionLog records older than configured retention period."""
    retention_days = _get_rule_log_retention_days()
    cutoff = timezone.now() - timedelta(days=retention_days)

    deleted_count, _ = RuleActionLog.objects.filter(fired_at__lt=cutoff).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d rule action logs older than %d days",
            deleted_count,
            retention_days,
        )

    return deleted_count
```

### Configuration
Add to `settings_registry.py`:
```python
SystemConfigSetting(
    key="rule_logs.retention_days",
    name="Rule log retention (days)",
    value_type="integer",
    default=14,
    description="Number of days to retain rule execution logs before automatic cleanup",
)
```

### Management Command
```bash
python manage.py run_task cleanup_rule_action_logs
```

## Consequences

### Positive
- Prevents unbounded table growth
- Consistent with event cleanup pattern
- Configurable retention period
- Reduces storage costs over time

### Negative
- Historical rule debugging limited to retention window
- Must ensure retention is long enough for typical debugging needs

### Mitigations
- Default 14-day retention balances storage with debugging needs
- Admins can increase retention if needed
- Consider adding export functionality before cleanup for audit requirements

## Todos
- [x] Add `rule_logs.retention_days` to `settings_registry.py`
- [x] Implement `cleanup_rule_action_logs` task in `alarm/tasks.py`
- [x] Add tests for the cleanup task
- [x] Add index on `fired_at` if not present (for efficient range queries) - already exists
