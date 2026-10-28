"""Background tasks for the locks app."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
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

    Unresolved ``clear_failed`` and in-window ``push_unconfirmed`` events are
    kept: they're the only record of a slot that may still hold a PIN.

    Returns the count of deleted records.
    """
    from locks.use_cases.lock_push import retained_marker_event_ids

    retention_days = _get_door_code_event_retention_days()
    if retention_days <= 0:
        return 0

    cutoff = timezone.now() - timedelta(days=retention_days)
    keep = retained_marker_event_ids(older_than=cutoff)
    deleted_count, _ = DoorCodeEvent.objects.filter(created_at__lt=cutoff).exclude(id__in=keep).delete()

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
    description="Re-attempt programming pending door codes onto physical locks.",
)
def push_pending_door_codes() -> int:
    """Iterate over pending door codes with unassigned slots or failed clears and retry them.

    A code is considered "pending" if (a) ``push_state=pending`` AND (b) it's
    active with at least one assignment still at ``slot_index IS NULL``, or it
    has a slot clear on record that failed (issue #139; active or not, since an
    inactive code's PIN may still be on the lock). Failed clears are retried
    before the push. The use case mutates per-row state; this task is the safety
    net for transient gateway failures.

    Returns the number of codes attempted this tick.
    """
    from locks.use_cases.lock_push import (
        push_or_settle_after_clear_retry,
        retry_failed_slot_clears,
        settle_clear_failure_state,
    )

    max_attempts = _get_push_max_attempts()

    unassigned_subquery = DoorCodeLockAssignment.objects.filter(
        door_code=OuterRef("pk"),
        slot_index__isnull=True,
    )
    # Any recorded clear failure, settled or not; retry_failed_slot_clears skips settled ones.
    clear_failed_subquery = DoorCodeEvent.objects.filter(
        door_code=OuterRef("pk"),
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata__action="clear_failed",
    )
    pending = (
        DoorCode.objects.annotate(
            _has_unassigned=Exists(unassigned_subquery),
            _has_clear_failures=Exists(clear_failed_subquery),
        )
        .filter(push_state=DoorCode.PushState.PENDING)
        .filter(Q(_has_unassigned=True, is_active=True) | Q(_has_clear_failures=True))
        .prefetch_related("lock_assignments")
    )

    attempted = 0
    for code in pending:
        try:
            clear_failures = retry_failed_slot_clears(door_code=code, zwavejs=default_zwavejs_gateway)
            successes, failures = push_or_settle_after_clear_retry(
                door_code=code,
                zwavejs=default_zwavejs_gateway,
                actor_user=None,
            )
        except Exception:
            logger.exception("Unexpected error retrying push for door code id=%d", code.id)
            continue
        failures = failures + [(f.lock_entity_id, f.reason) for f in clear_failures]

        attempted += 1
        # ``push_door_code_to_assigned_locks`` already increments ``push_attempt_count``
        # via _record_push_failure for each transient failure and resets it on success.
        code.refresh_from_db(fields=["push_state", "push_attempt_count", "last_push_error"])

        if not successes and failures and max_attempts > 0 and code.push_attempt_count >= max_attempts:
            # Consecutive-failure cap reached — give up and surface to operators.
            # Sanitize the upstream failure reason in case it ever carries PIN-shaped
            # digits (today none of the raised exception classes do, but defense
            # in depth — see sanitize_push_error_for_storage docstring).
            from locks.use_cases.lock_push import sanitize_push_error_for_storage

            safe_reason = sanitize_push_error_for_storage(failures[0][1])
            code.push_state = DoorCode.PushState.FAILED
            code.last_push_error = (f"Push gave up after {code.push_attempt_count} attempts: {safe_reason}")[:500]
            code.save(update_fields=["push_state", "last_push_error", "updated_at"])
            DoorCodeEvent.objects.create(
                door_code=code,
                user=code.user,
                event_type=DoorCodeEvent.EventType.CODE_FAILED,
                metadata={
                    "action": "push",
                    "reason": "max_attempts_exceeded",
                    "attempts": code.push_attempt_count,
                    "last_error": safe_reason[:200],
                },
            )
            # Lead with any slot that may still hold the PIN.
            settle_clear_failure_state(door_code=code)

    return attempted
