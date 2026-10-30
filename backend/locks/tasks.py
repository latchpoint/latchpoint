"""Background tasks for the locks app."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.system_config_utils import get_int_system_config_value
from scheduler import DailyAt, Every, register

from .models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from .use_cases.code_lifecycle import expired_q, started_q

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
    connections=("zwavejs",),
)
def push_pending_door_codes() -> int:
    """Iterate over pending door codes with unassigned slots or failed clears and retry them.

    A code is considered "pending" if (a) ``push_state=pending`` AND (b) it's
    active, started and not expired (issue #145) with at least one assignment
    still at ``slot_index IS NULL``, or it has a slot clear on record that failed (issue #139; active or not, since an
    inactive code's PIN may still be on the lock). An inactive manual code that
    still holds a slot or has an unconfirmed attempt slot left to check is
    picked up too, ``pending`` or ``pushed`` (issue #158), and those slots get
    cleared. Failed clears are retried before the push. The use case mutates
    per-row state; this task is the safety net for transient gateway failures.

    Returns the number of codes attempted this tick.
    """
    from locks.use_cases.lock_push import (
        inactive_slots_to_clear,
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
    # A rough cut for inactive codes; inactive_slots_to_clear has the exact rules.
    holds_slot_subquery = DoorCodeLockAssignment.objects.filter(
        door_code=OuterRef("pk"),
        slot_index__isnull=False,
    )
    unconfirmed_subquery = DoorCodeEvent.objects.filter(
        door_code=OuterRef("pk"),
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata__action="push_unconfirmed",
    )
    inactive_with_slots = Q(
        is_active=False,
        source=DoorCode.Source.MANUAL,
        push_state__in=[DoorCode.PushState.PENDING, DoorCode.PushState.PUSHED],
    ) & (Q(_holds_slot=True) | Q(_has_unconfirmed=True))
    # Only codes between their start_at and end_at get pushed (issue #145).
    now = timezone.now()
    to_push = Q(_has_unassigned=True, is_active=True) & started_q(now) & ~expired_q(now)
    pending = (
        DoorCode.objects.annotate(
            _has_unassigned=Exists(unassigned_subquery),
            _has_clear_failures=Exists(clear_failed_subquery),
            _holds_slot=Exists(holds_slot_subquery),
            _has_unconfirmed=Exists(unconfirmed_subquery),
        )
        .filter(
            Q(push_state=DoorCode.PushState.PENDING) & (to_push | Q(_has_clear_failures=True)) | inactive_with_slots
        )
        .prefetch_related("lock_assignments")
    )

    attempted = 0
    for code in pending:
        if code.push_state == DoorCode.PushState.PUSHED and not inactive_slots_to_clear(door_code=code):
            # Only picked up by the rough cut: nothing left on its locks to clear.
            continue
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
        try:
            code.refresh_from_db(fields=["push_state", "push_attempt_count", "last_push_error"])
        except DoorCode.DoesNotExist:
            # Deleted while this tick worked on it; nothing left to cap.
            logger.info("Door code id=%d was deleted during the push retry; skipping", code.id)
            continue

        if not successes and failures and max_attempts > 0 and code.push_attempt_count >= max_attempts:
            # Consecutive-failure cap reached — give up and surface to operators.
            # Sanitize the upstream failure reason in case it ever carries PIN-shaped
            # digits (today none of the raised exception classes do, but defense
            # in depth — see sanitize_push_error_for_storage docstring).
            from locks.use_cases.lock_push import sanitize_push_error_for_storage

            safe_reason = sanitize_push_error_for_storage(failures[0][1])
            code.push_state = DoorCode.PushState.FAILED
            code.last_push_error = (f"Push gave up after {code.push_attempt_count} attempts: {safe_reason}")[:500]
            with transaction.atomic():
                code.save(update_fields=["push_state", "last_push_error", "updated_at"])
                # Every lock of an active code still waiting on a push gave up with
                # the code, keeping its own error and count, so nothing starts
                # retrying on its own once the scheduler reads per-lock state
                # (issue #126). An inactive code is never pushed, so its locks
                # aren't waiting on one.
                DoorCodeLockAssignment.objects.filter(
                    door_code=code,
                    door_code__is_active=True,
                    push_state=DoorCode.PushState.PENDING,
                    slot_index__isnull=True,
                ).update(push_state=DoorCode.PushState.FAILED)
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


@register(
    "enforce_door_code_validity",
    schedule=Every(seconds=60),
    description="Takes door codes off their locks once they expire and puts them on once they start.",
    connections=("zwavejs",),
)
def enforce_door_code_validity() -> int:
    """Keep each door code's PIN on its locks only between its ``start_at`` and ``end_at`` (issue #145).

    Three passes against one ``now``, for codes of any source or type:

    - an active code at or past its ``end_at`` is retired: turned off through
      the same locked update a user's deactivate uses, so a clear that fails is
      left to ``push_pending_door_codes``'s retries
    - an active code whose ``start_at`` is still ahead but that may hold a slot
      (pushed before this was enforced, or its start moved later) has those
      slots cleared and stays active
    - an active code whose ``start_at`` has passed, that isn't expired, has a
      lock without a slot and hasn't had a push attempt since its start is
      pushed. The attempt is stamped either way, so a push that doesn't land
      is left to ``push_pending_door_codes`` instead of being tried every minute

    Errors are caught per code (a busy lock included) and the task never
    raises. Returns the number of codes it acted on.
    """
    from locks.use_cases.door_codes import retire_door_code, withdraw_door_code
    from locks.use_cases.lock_push import push_door_code_to_assigned_locks

    now = timezone.now()
    acted = 0

    for code in DoorCode.objects.filter(is_active=True).filter(expired_q(now)).order_by("id"):
        try:
            if retire_door_code(code=code, reason="expired", zwavejs=default_zwavejs_gateway, now=now) is not None:
                acted += 1
        except Exception:
            logger.warning("Couldn't retire expired door code id=%d this tick", code.id, exc_info=True)

    holds_slot = DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk"), slot_index__isnull=False)
    # Unconfirmed attempts nothing has settled since: no later push landed on that
    # lock, and no later marker says the slot was checked or emptied. A rough cut,
    # it can only match too much (slots_to_withdraw has the exact rules), so a
    # code whose markers are all settled isn't looked at every tick.
    settled_since = DoorCodeEvent.objects.filter(
        door_code=OuterRef("door_code"),
        lock_entity_id=OuterRef("lock_entity_id"),
        id__gt=OuterRef("id"),
    ).filter(
        Q(event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        | Q(metadata__action="unconfirmed_resolved", metadata__slot_index=OuterRef("metadata__slot_index"))
        | Q(
            metadata__action="clear_resolved",
            metadata__outcome__in=["cleared", "lock_missing"],
            metadata__slot_index=OuterRef("metadata__slot_index"),
        )
        | Q(
            # A clear retry that read the slot back empty settles it too (issues #128, #152).
            metadata__action="clear_resolved",
            metadata__slot_empty=True,
            metadata__slot_index=OuterRef("metadata__slot_index"),
        )
    )
    still_on_lock = DoorCodeLockAssignment.objects.filter(
        door_code=OuterRef("door_code"), lock_entity_id=OuterRef("lock_entity_id")
    )
    unconfirmed = (
        DoorCodeEvent.objects.filter(
            door_code=OuterRef("pk"),
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata__action="push_unconfirmed",
        )
        .filter(Exists(still_on_lock))
        .exclude(Exists(settled_since))
    )
    not_started = (
        DoorCode.objects.filter(is_active=True)
        .exclude(started_q(now))
        .filter(Exists(holds_slot) | Exists(unconfirmed))
        .order_by("id")
    )
    for code in not_started:
        try:
            if withdraw_door_code(code=code, zwavejs=default_zwavejs_gateway):
                acted += 1
        except Exception:
            logger.warning("Couldn't take door code id=%d off its locks before its start", code.id, exc_info=True)

    unassigned = DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk"), slot_index__isnull=True)
    just_started = (
        DoorCode.objects.filter(is_active=True, start_at__isnull=False, start_at__lte=now)
        .exclude(expired_q(now))
        .filter(Exists(unassigned))
        .filter(Q(last_push_attempt_at__isnull=True) | Q(last_push_attempt_at__lt=F("start_at")))
        .prefetch_related("lock_assignments")
        .order_by("id")
    )
    for code in just_started:
        try:
            push_door_code_to_assigned_locks(door_code=code, zwavejs=default_zwavejs_gateway, only_unassigned=True)
            acted += 1
        except Exception:
            logger.warning("Couldn't push door code id=%d at its start", code.id, exc_info=True)
        try:
            DoorCode.objects.filter(id=code.id).filter(
                Q(last_push_attempt_at__isnull=True) | Q(last_push_attempt_at__lt=F("start_at"))
            ).update(last_push_attempt_at=now)
        except Exception:
            logger.warning("Couldn't stamp the push attempt for door code id=%d", code.id, exc_info=True)

    return acted
