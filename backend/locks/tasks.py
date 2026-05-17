"""Background tasks for the locks app."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.system_config_utils import get_int_system_config_value
from scheduler import DailyAt, Every, register

from .models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment

logger = logging.getLogger(__name__)


def _get_door_code_event_retention_days() -> int:
    """Read door_code_events.retention_days from SystemConfig, fallback to default."""
    return get_int_system_config_value(key="door_code_events.retention_days")


def _get_push_max_attempts() -> int:
    """Read door_codes.push_max_attempts from SystemConfig, fallback to default (24)."""
    return get_int_system_config_value(key="door_codes.push_max_attempts")


@register(
    "cleanup_door_code_events",
    schedule=DailyAt(hour=3, minute=10),
    description="Deletes old door code audit events based on your retention settings.",
)
def cleanup_door_code_events() -> int:
    """
    Delete DoorCodeEvent records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_door_code_event_retention_days()
    if retention_days <= 0:
        return 0

    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = DoorCodeEvent.objects.filter(created_at__lt=cutoff).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d door code events older than %d days (cutoff: %s)",
            deleted_count,
            retention_days,
            cutoff.isoformat(),
        )

    return deleted_count


@register(
    "push_pending_door_codes",
    schedule=Every(seconds=300),
    failure_backoff_base_seconds=60,
    failure_backoff_max_seconds=3600,
    description="Re-attempt programming pending door codes onto physical locks (ADR 0092).",
)
def push_pending_door_codes() -> int:
    """Iterate over pending door codes with unassigned slots and retry the push.

    A code is considered "pending" if (a) ``push_state=pending`` AND (b) at least
    one assignment still has ``slot_index IS NULL``. The use case mutates per-row
    state; this task is the safety net for transient gateway failures.

    Returns the number of codes attempted this tick.
    """
    from locks.use_cases.lock_push import push_door_code_to_assigned_locks

    max_attempts = _get_push_max_attempts()

    unassigned_subquery = DoorCodeLockAssignment.objects.filter(
        door_code=OuterRef("pk"),
        slot_index__isnull=True,
    )
    pending = (
        DoorCode.objects.annotate(_has_unassigned=Exists(unassigned_subquery))
        .filter(push_state=DoorCode.PushState.PENDING, _has_unassigned=True, is_active=True)
        .prefetch_related("lock_assignments")
    )

    attempted = 0
    for code in pending:
        try:
            successes, failures = push_door_code_to_assigned_locks(
                door_code=code,
                zwavejs=default_zwavejs_gateway,
                actor_user=None,
                only_unassigned=True,
            )
        except Exception:
            logger.exception("Unexpected error retrying push for door code id=%d", code.id)
            continue

        attempted += 1
        # ``push_door_code_to_assigned_locks`` already increments ``push_attempt_count``
        # via _record_push_failure for each transient failure and resets it on success.
        code.refresh_from_db(fields=["push_state", "push_attempt_count", "last_push_error"])

        if not successes and failures and max_attempts > 0 and code.push_attempt_count >= max_attempts:
            # Consecutive-failure cap reached — give up and surface to operators.
            code.push_state = DoorCode.PushState.FAILED
            code.last_push_error = (f"Push gave up after {code.push_attempt_count} attempts: {failures[0][1]}")[:500]
            code.save(update_fields=["push_state", "last_push_error", "updated_at"])
            DoorCodeEvent.objects.create(
                door_code=code,
                user=code.user,
                event_type=DoorCodeEvent.EventType.CODE_FAILED,
                metadata={
                    "action": "push",
                    "reason": "max_attempts_exceeded",
                    "attempts": code.push_attempt_count,
                    "last_error": failures[0][1][:200],
                },
            )

    return attempted
