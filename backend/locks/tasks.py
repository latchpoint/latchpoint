"""Background tasks for the locks app."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import Error as DbError
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.system_config_utils import get_int_system_config_value
from scheduler import DailyAt, Every, register

from .models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from .use_cases.code_lifecycle import belongs_on_lock, expired_q, started_q

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
    """Retry the door code pushes and clears that haven't landed, lock by lock (issue #126).

    Each tick first repairs per-lock state that drifted from its slot
    (``normalize_assignment_push_state``) and fails every lock still waiting on
    a push whose own attempt count reached ``door_codes.push_max_attempts``
    (``sweep_push_cap``, again after the attempts). Then a code is picked up when

    - it's active, started and not expired (issue #145) and one of its locks
      is ``pending`` with no slot or a pending schedule (issue #123) and under
      the cap. The code's own ``push_state`` doesn't matter, so a terminal
      failure on one lock doesn't stop the retries of another
    - it has a slot clear on record that failed (issue #139; active or not,
      since an inactive code's PIN may still be on the lock), while its
      clear-retry count is under the cap
    - it's an inactive manual code that still holds a slot or has an
      unconfirmed attempt slot left to check, ``pending`` or ``pushed`` (issue
      #158), and those slots get cleared
    - it's a synced code with an unsettled unconfirmed attempt on one of its
      locks (issue #180). Lock sync skips it there while that's on record, so
      the attempt slots are read back, read only, and settled when they don't
      hold the PIN (``check_synced_attempt_slots``)

    Failed clears are retried before the push. The use cases record each
    lock's outcome and the code's rollup; this task is the safety net for
    transient gateway failures. Returns the number of codes attempted this tick.
    """
    from locks.use_cases.lock_push import (
        being_removed_q,
        check_synced_attempt_slots,
        inactive_slots_to_clear,
        locks_to_push,
        normalize_assignment_push_state,
        push_or_settle_after_clear_retry,
        retry_failed_slot_clears,
        sanitize_push_error_for_storage,
        sweep_push_cap,
        synced_attempt_slots_to_check,
        unresolved_clear_failures,
    )

    max_attempts = _get_push_max_attempts()
    # One now for the whole tick: the arms below and both cap sweeps (PR #195 review).
    now = timezone.now()

    normalize_assignment_push_state()
    sweep_push_cap(now=now, max_attempts=max_attempts)

    # Not a lock the code is being dropped from: nothing ever pushes it, so it
    # would pick the code every tick and run its clear retries past the cap (PR #196 review).
    needs_push_subquery = (
        DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk"), push_state=DoorCode.PushState.PENDING)
        .filter(Q(slot_index__isnull=True) | Q(schedule_pending=True))
        .exclude(being_removed_q())
    )
    if max_attempts > 0:
        # Belt and braces: the sweep above already failed every waiting lock at
        # the cap, but a push outside the scheduler can count one up since.
        needs_push_subquery = needs_push_subquery.filter(push_attempt_count__lt=max_attempts)
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
    # A rough cut too; synced_attempt_slots_to_check has the exact rules (issue #180).
    synced_with_attempts = Q(source=DoorCode.Source.SYNCED, _has_unconfirmed=True)
    # Only codes between their start_at and end_at get pushed (issue #145).
    to_push = Q(_needs_push=True, is_active=True) & started_q(now) & ~expired_q(now)
    clears_to_retry = Q(_has_clear_failures=True)
    if max_attempts > 0:
        # The clear-retry cap stays at code level (issue #126).
        clears_to_retry &= Q(push_attempt_count__lt=max_attempts)
    candidates = (
        DoorCode.objects.annotate(
            _needs_push=Exists(needs_push_subquery),
            _has_clear_failures=Exists(clear_failed_subquery),
            _holds_slot=Exists(holds_slot_subquery),
            _has_unconfirmed=Exists(unconfirmed_subquery),
        )
        .filter(to_push | clears_to_retry | inactive_with_slots | synced_with_attempts)
        .prefetch_related("lock_assignments")
        .order_by("id")
    )

    attempted = 0
    for code in candidates:
        # The exact rules on top of the SQL rough cut, ie not a slot whose clear is still outstanding.
        picked_to_push = (
            code._needs_push
            and code.is_active
            and belongs_on_lock(code, now=now)
            and any(
                max_attempts <= 0 or assignment.push_attempt_count < max_attempts
                for assignment in locks_to_push(door_code=code, assignments=list(code.lock_assignments.all()))
            )
        )
        # The clear retries only run under the code's clear-retry cap, whichever
        # arm picked the code (PR #196 review).
        clears_due = bool(unresolved_clear_failures(door_code=code)) and (
            max_attempts <= 0 or (code.push_attempt_count or 0) < max_attempts
        )
        synced_checks_due = bool(synced_attempt_slots_to_check(door_code=code))
        if (
            not picked_to_push
            and not clears_due
            and not synced_checks_due
            and not inactive_slots_to_clear(door_code=code)
        ):
            # Only picked up by a rough cut (a settled clear failure, a slot of an
            # inactive code with nothing left to clear): nothing to do on its locks.
            continue
        was_failed = code.push_state == DoorCode.PushState.FAILED
        try:
            clear_failures = (
                retry_failed_slot_clears(door_code=code, zwavejs=default_zwavejs_gateway) if clears_due else []
            )
            if synced_checks_due:
                check_synced_attempt_slots(door_code=code, zwavejs=default_zwavejs_gateway)
            _successes, failures = push_or_settle_after_clear_retry(
                door_code=code,
                zwavejs=default_zwavejs_gateway,
                actor_user=None,
            )
        except Exception:
            logger.exception("Unexpected error retrying push for door code id=%d", code.id)
            continue
        # What the code-level count counts: the clear retries, and an inactive code's clears.
        clear_failures_this_tick = [(f.lock_entity_id, f.reason) for f in clear_failures]
        if not code.is_active:
            clear_failures_this_tick += failures

        attempted += 1
        try:
            code.refresh_from_db(fields=["push_state", "push_attempt_count", "last_push_error"])
        except DoorCode.DoesNotExist:
            # Deleted while this tick worked on it; nothing left to cap.
            logger.info("Door code id=%d was deleted during the push retry; skipping", code.id)
            continue

        if (
            not was_failed
            and code.push_state == DoorCode.PushState.FAILED
            and clear_failures_this_tick
            and max_attempts > 0
            and code.push_attempt_count >= max_attempts
        ):
            # The rollup gave up on the clears at the cap; surface it to operators.
            # Sanitized in case a reason ever carries PIN-shaped digits.
            DoorCodeEvent.objects.create(
                door_code=code,
                user=code.user,
                event_type=DoorCodeEvent.EventType.CODE_FAILED,
                metadata={
                    "action": "push",
                    "reason": "max_attempts_exceeded",
                    "attempts": code.push_attempt_count,
                    "last_error": sanitize_push_error_for_storage(clear_failures_this_tick[0][1])[:200],
                },
            )

    # Locks this tick's failures took to the cap.
    sweep_push_cap(now=now, max_attempts=max_attempts)
    return attempted


# How long the queued push task waits for a lock someone else holds before moving
# on. The lock stays queued, so the next 5s tick waits for it again (issue #124).
_QUEUED_PUSH_LOCK_WAIT_SECONDS = 10.0


def _pushable_q(now) -> Q:
    """A code something would push at ``now``: active, started and not expired."""
    return Q(is_active=True) & started_q(now) & ~expired_q(now)


def _requester(assignment: DoorCodeLockAssignment | None):
    """Who queued the push, or ``None`` when no one did or that user is gone.

    ``push_requested_by`` has no DB constraint (migration 0011), so a user
    deleted by code from before it leaves the id dangling. It's read by id
    rather than through the relation, which would raise for that.
    """
    from accounts.models import User

    if assignment is None or assignment.push_requested_by_id is None:
        return None
    return User.objects.filter(id=assignment.push_requested_by_id).first()


@register(
    "push_requested_door_codes",
    schedule=Every(seconds=5, jitter=1),
    description="Pushes door codes onto their locks right after they're saved or retried.",
    connections=("zwavejs",),
    # Many slow locks can add up, but a run this long is stuck (PR #201 review).
    max_runtime_seconds=600,
)
def push_requested_door_codes() -> int:
    """Push the locks a create, update or Retry queued with ``request_push``, lock by lock (issue #124).

    Woken by ``scheduler.runner.wake_task`` once the save commits, so a queued
    push goes out within moments, and the 5s tick is the backstop. The locks are
    ``queued_push_assignments`` (one cheap query when there's nothing queued,
    ADR-0103) and ``locks_to_push``'s rule on top. Each lock is pushed on its
    own: the task waits up to ``_QUEUED_PUSH_LOCK_WAIT_SECONDS`` for its
    ``lock_sync:`` lock, checks it's still queued once it holds it (a push that
    got there first used the request up), and pushes through a
    ``BudgetedGateway``, so a slow lock gives up after
    ``PUSH_LOCK_BUDGET_SECONDS`` and is left ``pending`` without the attempt
    counting toward the cap. An attempt that ran counts like any other push. A
    lock still busy at the wait stays queued for the next tick, until the
    request lapses after ``PUSH_REQUEST_TTL`` and ``push_pending_door_codes``
    has it. A push that ran out of budget during the schedule right after its
    ``set`` is queued once more, so the schedule follows on the next tick. A
    lock dropped while the task waited sends nothing and the code's other
    locks carry on, unless the code itself is gone, off or out of its dates. The
    ``code_synced`` event's actor is whoever queued it (no one, when that user
    is gone), and each code ends with ``refresh_push_state``. Errors are caught
    per lock and per code. Returns the number of locks it tried.
    """
    from locks.use_cases.lock_config_sync import LockBusy, hold_lock_sync, sync_lock_deadline
    from locks.use_cases.lock_push import (
        PUSH_LOCK_BUDGET_SECONDS,
        BudgetedGateway,
        InvalidPin,
        LockPushFailed,
        LockSlotsFull,
        LockUnreachable,
        PushSuperseded,
        locks_to_push,
        push_door_code_to_lock,
        queued_push_assignments,
        refresh_push_state,
    )

    now = timezone.now()
    # Idle fast path (ADR-0103): one query, before the cap is even read.
    if not queued_push_assignments(now=now, max_attempts=0).exists():
        return 0
    queued = queued_push_assignments(now=now, max_attempts=_get_push_max_attempts())

    attempted = 0
    for code_id in sorted(set(queued.values_list("door_code_id", flat=True))):
        code = DoorCode.objects.filter(id=code_id).first()
        if code is None:
            continue
        try:
            lock_entity_ids = [
                a.lock_entity_id
                for a in locks_to_push(
                    door_code=code, assignments=list(queued.filter(door_code_id=code_id).order_by("lock_entity_id"))
                )
            ]
            for lock_entity_id in lock_entity_ids:
                try:
                    with hold_lock_sync([lock_entity_id], deadline=sync_lock_deadline(_QUEUED_PUSH_LOCK_WAIT_SECONDS)):
                        current = DoorCodeLockAssignment.objects.filter(
                            door_code_id=code_id, lock_entity_id=lock_entity_id
                        ).first()
                        if current is not None and not queued.filter(id=current.id).exists():
                            # Pushed, tried or changed (failed, say) while this waited for the lock.
                            continue
                        # A code deleted or a lock dropped meanwhile goes through the push
                        # too, which finds that out and raises PushSuperseded with nothing sent.
                        attempted += 1
                        push_door_code_to_lock(
                            door_code=code,
                            lock_entity_id=lock_entity_id,
                            zwavejs=BudgetedGateway(default_zwavejs_gateway, seconds=PUSH_LOCK_BUDGET_SECONDS),
                            actor_user=_requester(current),
                        )
                except LockBusy:
                    logger.info(
                        "Queued push of door code id=%d to %s is still waiting for the lock", code_id, lock_entity_id
                    )
                except PushSuperseded:
                    if not DoorCode.objects.filter(id=code_id).filter(_pushable_q(timezone.now())).exists():
                        logger.info("Door code id=%d changed while its queued push waited; stopping", code_id)
                        break
                    # Only this lock was dropped meanwhile; the code's other locks still get theirs.
                    logger.info("Queued push of door code id=%d to %s was superseded", code_id, lock_entity_id)
                except (LockUnreachable, LockSlotsFull, LockPushFailed, InvalidPin):
                    # Recorded on the lock by the push itself.
                    pass
                except Exception:
                    logger.exception("Unexpected error pushing queued door code id=%d to %s", code_id, lock_entity_id)
            refresh_push_state(door_code=code)
        except Exception:
            logger.exception("Unexpected error in the queued push of door code id=%d", code_id)

    return attempted


def _open_clear_failure_events():
    """A code's ``clear_failed`` events no later ``clear_failed`` or ``clear_resolved`` for the slot replaced.

    For an ``Exists`` on ``DoorCode``, the same newest-event-wins rule as
    ``unresolved_clear_failures`` (and ``being_removed_q``).
    """
    replaced = DoorCodeEvent.objects.filter(
        door_code=OuterRef("door_code"),
        lock_entity_id=OuterRef("lock_entity_id"),
        metadata__action__in=["clear_failed", "clear_resolved"],
        metadata__slot_index=OuterRef("metadata__slot_index"),
        id__gt=OuterRef("id"),
    )
    return DoorCodeEvent.objects.filter(door_code=OuterRef("pk"), metadata__action="clear_failed").exclude(
        Exists(replaced)
    )


def _load_validity_pass(codes) -> list[DoorCode] | None:
    """Run one of ``enforce_door_code_validity``'s querysets, or log a DB error and give ``None`` (issue #186).

    Building a queryset doesn't touch the DB, so this is where one fails.
    ``django.db.Error`` rather than ``DatabaseError``, since a dropped
    connection can come back as ``InterfaceError``, which isn't one.
    """
    try:
        return list(codes)
    except DbError:
        logger.warning("Couldn't load door codes to enforce their validity this tick", exc_info=True)
        return None


@register(
    "enforce_door_code_validity",
    schedule=Every(seconds=60),
    description="Takes door codes off their locks once they expire and puts them on once they start.",
    connections=("zwavejs",),
)
def enforce_door_code_validity() -> int:
    """Keep each door code's PIN on its locks only between its ``start_at`` and ``end_at`` (issue #145).

    Four passes against one ``now``, for codes of any source or type:

    - an active code at or past its ``end_at`` is retired: turned off through
      the same locked update a user's deactivate uses, so a clear that fails is
      left to ``push_pending_door_codes``'s retries. Stranded synced copies of
      its PIN go with it, and one whose retire raised is tried again on later
      ticks (``retry_pending_copy_retires``)
    - an active code whose ``start_at`` is still ahead but that may hold a slot
      (pushed before this was enforced, or its start moved later) has those
      slots cleared and stays active
    - an active code whose ``start_at`` has passed, that isn't expired, has a
      lock still waiting for its ``set`` or schedule and hasn't had a push
      attempt since its start is pushed. Its ``failed`` locks are re-armed
      first, since only the 0010 backfill fails a lock before its code starts.
      The attempt is stamped either way, so a push that doesn't land is left
      to ``push_pending_door_codes`` instead of being tried every minute
    - an active started code that's ``failed`` with no ``failed`` lock, no
      clear failure still open and no push attempt since its start, ie one the
      withdraw failed at the cap, gets its rollup refreshed (once, since that
      takes it out of ``failed``)

    Errors are caught per code (a busy lock included) and the task never
    raises. A DB error while loading a pass's codes is logged and the tick
    ends there, the next tick starting over (issue #186). Returns the number
    of codes it acted on.
    """
    from locks.use_cases.door_codes import retire_door_code, retry_pending_copy_retires, withdraw_door_code
    from locks.use_cases.lock_push import push_door_code_to_assigned_locks, rearm_failed_locks, refresh_push_state

    now = timezone.now()
    acted = 0

    expired = _load_validity_pass(DoorCode.objects.filter(is_active=True).filter(expired_q(now)).order_by("id"))
    if expired is None:
        return acted
    for code in expired:
        try:
            if retire_door_code(code=code, reason="expired", zwavejs=default_zwavejs_gateway, now=now) is not None:
                acted += 1
        except Exception:
            logger.warning("Couldn't retire expired door code id=%d this tick", code.id, exc_info=True)

    # Stranded synced copies a retire couldn't take off last time (PR #211 review).
    try:
        acted += retry_pending_copy_retires(zwavejs=default_zwavejs_gateway)
    except Exception:
        logger.warning("Couldn't retry the pending retires of synced copies this tick", exc_info=True)

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
    not_started = _load_validity_pass(
        DoorCode.objects.filter(is_active=True)
        .exclude(started_q(now))
        .filter(Exists(holds_slot) | Exists(unconfirmed))
        .order_by("id")
    )
    if not_started is None:
        return acted
    for code in not_started:
        try:
            if withdraw_door_code(code=code, zwavejs=default_zwavejs_gateway):
                acted += 1
        except Exception:
            logger.warning("Couldn't take door code id=%d off its locks before its start", code.id, exc_info=True)

    # A lock still waiting for its set or its schedule (issue #123). Failed ones
    # count too: before its start nothing pushes a code, so a lock is only failed
    # then because the 0010 backfill copied the code's failure onto it, and it
    # gets re-armed below so the code still goes on its locks (PR #195 review).
    waiting = DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk")).filter(
        Q(push_state=DoorCode.PushState.PENDING) | Q(push_state=DoorCode.PushState.FAILED),
        Q(slot_index__isnull=True) | Q(schedule_pending=True),
    )
    just_started = _load_validity_pass(
        DoorCode.objects.filter(is_active=True, start_at__isnull=False, start_at__lte=now)
        .exclude(expired_q(now))
        .filter(Exists(waiting))
        .filter(Q(last_push_attempt_at__isnull=True) | Q(last_push_attempt_at__lt=F("start_at")))
        .prefetch_related("lock_assignments")
        .order_by("id")
    )
    if just_started is None:
        return acted
    for code in just_started:
        try:
            if rearm_failed_locks(door_code=code):
                code = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
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

    # A code the withdraw failed at the clear-retry cap before its start, whose
    # locks all kept their slots (a readback that never answered), has nothing
    # waiting for a push at its start, so nothing worked its rollup out again
    # and it stayed failed with the stale "may still hold the PIN" error (PR
    # #207 review). Its rollup is refreshed once it starts. Only codes the
    # rollup would take out of failed are looked at, so each is refreshed once
    # (PR #211 review): a failed lock is left to Retry, and so is a clear failure
    # still open, which keeps the code failed at the cap.
    failed_lock = DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk"), push_state=DoorCode.PushState.FAILED)
    capped_before_start = _load_validity_pass(
        DoorCode.objects.filter(
            is_active=True, push_state=DoorCode.PushState.FAILED, start_at__isnull=False, start_at__lte=now
        )
        .exclude(expired_q(now))
        .exclude(Exists(failed_lock))
        .exclude(Exists(_open_clear_failure_events()))
        .filter(Q(last_push_attempt_at__isnull=True) | Q(last_push_attempt_at__lt=F("start_at")))
        .order_by("id")
    )
    if capped_before_start is None:
        return acted
    for code in capped_before_start:
        try:
            if refresh_push_state(door_code=code) not in (None, DoorCode.PushState.FAILED):
                acted += 1
        except Exception:
            logger.warning("Couldn't refresh door code id=%d at its start", code.id, exc_info=True)

    return acted
