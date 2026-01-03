# ADR-0029: Session Cleanup Task

## Status
Implemented

## Context
Django stores session data in the database by default (`django.contrib.sessions.backends.db`). Each authenticated user session creates a row in `django_session` table containing:
- Session key (primary key)
- Session data (pickled/JSON)
- Expiry datetime

### Problem
Expired sessions are not automatically deleted. Over time:
- The `django_session` table grows unbounded
- Stale sessions consume database storage
- Query performance can degrade on large session tables

Django provides `python manage.py clearsessions` to remove expired sessions, but this requires manual execution or external cron scheduling.

### Current State
- Sessions are database-backed (Django default)
- Session expiry is configured via `SESSION_COOKIE_AGE` (default: 2 weeks)
- No automated cleanup mechanism

## Decision
Add a scheduled task `cleanup_expired_sessions` that wraps Django's `clearsessions` command.

### Implementation

```python
# backend/alarm/tasks.py
from scheduler import register, DailyAt

@register("cleanup_expired_sessions", schedule=DailyAt(hour=4, minute=0))
def cleanup_expired_sessions() -> int:
    """
    Delete expired Django sessions from the database.

    Wraps Django's clearsessions management command.
    Returns the count of deleted sessions.
    """
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    # Count expired sessions before deletion
    expired_count = Session.objects.filter(expire_date__lt=timezone.now()).count()

    if expired_count == 0:
        logger.debug("No expired sessions to clean up")
        return 0

    # Use Django's built-in cleanup
    from django.core.management import call_command
    call_command("clearsessions", verbosity=0)

    logger.info("Cleaned up %d expired sessions", expired_count)
    return expired_count
```

### Schedule
- **Time**: Daily at 4:00 AM
- **Rationale**: Low-traffic period; runs after other cleanup tasks (events at 3:00, rule logs at 3:30)

### Alternative Implementation
Direct deletion instead of management command:
```python
def cleanup_expired_sessions() -> int:
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    deleted_count, _ = Session.objects.filter(expire_date__lt=timezone.now()).delete()
    return deleted_count
```

## Alternatives Considered

### External cron job
- **Pros**: Simple, well-understood
- **Cons**: Requires separate scheduling infrastructure; not portable
- **Verdict**: In-process scheduler is simpler for this use case

### Cache-based sessions (no cleanup needed)
- **Pros**: Automatic expiry handled by cache backend
- **Cons**: Requires Redis/Memcached; sessions lost on cache eviction
- **Verdict**: Database sessions are fine for this application's scale

### More frequent cleanup
- **Pros**: Smaller session table at any given time
- **Cons**: Unnecessary overhead; sessions don't accumulate that fast
- **Verdict**: Daily is sufficient for typical usage patterns

## Consequences

### Positive
- Bounded session table growth
- Consistent with other cleanup tasks
- Zero configuration (uses Django's built-in logic)

### Negative
- Additional daily database writes
- Minimal: expired sessions don't cause issues until table is very large

### Mitigations
- Running at 4 AM minimizes user impact
- Deletion is efficient (indexed on expire_date)

## Todos
- [ ] Implement `cleanup_expired_sessions` task in `alarm/tasks.py`
- [ ] Add test for the cleanup task
- [ ] Verify `django_session` table has index on `expire_date` (Django default)
