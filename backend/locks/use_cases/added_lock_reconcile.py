"""Bring a synced code's added locks in line with its PIN and schedule (issue #220, ADR 0082).

A synced code's PIN and schedule come from the lock it was imported from. Lock
sync of that lock only flags the code's other locks (the ones someone added in
latchpoint, which got the PIN from a push) with ``reconcile_requested_at``
(:func:`flag_added_locks`) and wakes the queued push task. It sends nothing to
them, since it only holds the import lock's ``lock_sync:`` lock.

:func:`reconcile_added_lock` then owns every change to such a lock. It runs
under that lock's ``lock_sync:`` lock and each time reads the code's current
PIN and schedule and the slot's real contents live, then compares them with
what latchpoint last wrote there (``written_pin`` and ``written_schedule``,
recorded by every push):

- the slot holds the code's PIN: it's kept. When the schedule latchpoint wrote
  isn't the code's, the new one is sent into the slot if it keeps every day the
  written one had, and otherwise the slot is cleared and pushed again, since the
  schedule push never takes a day away
- the slot holds the PIN latchpoint last wrote there, or a code the lock won't
  show: it's latchpoint's old PIN, so it's cleared and the code pushed again
- the slot holds another PIN (typed in at the keypad, say), or nothing: it's let
  go untouched and the code is pushed into a free slot
- no slot: the code is pushed, which adopts an unconfirmed attempt holding its PIN

Before any push, slots an unconfirmed push may have left an older PIN in are
read back and cleared when they hold it. A lock where another code already has
the code's PIN is failed for a human instead of pushed (issue #188), once the
old PIN is off it. A code that's off, not started, expired or being dropped
from the lock is left for later (ADR-0109). The flag is only cleared when it's
still the one this run read, so a sync that flags the lock again meanwhile gets
another run. Failures count on the lock's attempts, never as clear failures, so
they don't hold back the import lock's sync.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone as django_timezone

from alarm.crypto import SettingsEncryption
from config.domain_exceptions import GatewayError
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.use_cases.code_lifecycle import belongs_on_lock, expired_q, started_q

logger = logging.getLogger(__name__)

# The lock's error while it waits for its reconcile.
WAITING_ERROR = "Waiting to send the code's new PIN or schedule to this lock."

# reconcile_added_lock outcomes.
NOTHING = "nothing"  # not flagged, or the code or lock is gone
WAITING = "waiting"  # off, outside its dates or being dropped; left flagged
IN_LINE = "in_line"  # already matched, marked pushed
PUSHED = "pushed"  # sent what was missing
HELD = "held"  # another code has the PIN there; failed for a human
RETRY = "retry"  # transient failure, still flagged
FAILED = "failed"  # terminal failure, still flagged until Retry or another change

# What a live read of the tracked slot found, against the code's PIN and the one latchpoint wrote.
_CURRENT = "current"
_STALE = "stale"
_OTHER = "other"
_EMPTY = "empty"


class _Transient(Exception):
    """A read or clear that got no usable answer; the lock stays flagged and is tried again."""


def schedule_only_grows(*, old_days: int | None, new_days: int | None) -> bool:
    """Whether sending the ``new_days`` schedule over the ``old_days`` one leaves nothing of the old behind.

    The schedule push writes one CC 78 entry per enabled weekday, in a slot of
    its own per weekday, so it overwrites every day it keeps and adds new ones
    but never takes one away. True when the new schedule has every day the old
    one had, a first schedule included, false when it drops a day or goes away.
    """
    return new_days is not None and not (int(old_days or 0) & ~int(new_days))


def _days_of(fingerprint: str | None) -> int | None:
    if not fingerprint:
        return None
    return int(fingerprint.split("|", 1)[0])


def pin_held_by_another_code(
    *, door_code: DoorCode, lock_entity_id: str, pin: str | None = None
) -> DoorCodeLockAssignment | None:
    """Another code's assignment on this lock that has ``pin`` (``door_code``'s own by default), or ``None``.

    That's a code holding it in a slot there, or one active there and waiting
    for its push, the rule turning a code on and adding a lock use (issue #188).
    """
    from locks.use_cases.lock_push import decrypt_pin_or_none

    pin = pin if pin is not None else decrypt_pin_or_none(door_code)
    if not pin:
        return None
    others = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(lock_entity_id=lock_entity_id)
        .exclude(door_code=door_code)
        .order_by("door_code_id")
    )
    for assignment in others:
        if assignment.slot_index is None and not assignment.door_code.is_active:
            continue
        if decrypt_pin_or_none(assignment.door_code) == pin:
            return assignment
    return None


def held_pin_error(assignment: DoorCodeLockAssignment) -> str:
    """The lock error for a code kept off a lock because ``assignment``'s code has its PIN there. No PIN in it."""
    from locks.use_cases.lock_push import sanitize_push_error_for_storage

    other = assignment.door_code
    name = f'door code {other.id} ("{other.label}")' if other.label else f"door code {other.id}"
    where = f"in slot {assignment.slot_index}" if assignment.slot_index is not None else "waiting to be pushed"
    return sanitize_push_error_for_storage(
        f"{assignment.lock_entity_id} already has this PIN {where} as {name}, so this code is off that lock. "
        "Delete that code, then Retry."
    )


def flag_added_locks(
    *,
    door_code: DoorCode,
    import_lock_entity_id: str,
    out_of_date_only: bool = False,
    now: datetime | None = None,
) -> list[str]:
    """Flag ``door_code``'s locks other than ``import_lock_entity_id`` for :func:`reconcile_added_lock`.

    For lock sync, once it has taken a new PIN or schedule from the lock the
    code was imported from. Each lock is re-armed (``pending``, no attempts, the
    :data:`WAITING_ERROR`), which also brings back one a held PIN or the
    attempt cap failed, and the queued push task is woken once the caller's
    transaction commits. A lock the code is being dropped from is left to its
    clear. The code row is taken first, like every writer of a code's
    assignments. Returns the locks flagged.

    ``out_of_date_only`` is for a code lock sync just turned back on: only the
    locks still flagged, with no slot, or whose slot isn't known to hold the
    code's PIN and schedule are flagged (again, from now), so the queued push
    task takes them up at once however long the code was off (review of PR #223).
    """
    from locks.use_cases.lock_push import (
        _lock_code_row,
        _locks_being_removed,
        _wake_push_task,
        code_schedule_fingerprint,
        decrypt_pin_or_none,
    )

    now = now or django_timezone.now()
    with transaction.atomic():
        _lock_code_row(door_code.id)
        others = (
            DoorCodeLockAssignment.objects.filter(door_code=door_code)
            .exclude(lock_entity_id=import_lock_entity_id)
            .exclude(lock_entity_id__in=_locks_being_removed(door_code=door_code))
        )
        if out_of_date_only:
            pin = decrypt_pin_or_none(door_code)
            desired = code_schedule_fingerprint(door_code)
            behind = [
                a.id
                for a in others
                if a.reconcile_requested_at is not None
                or a.slot_index is None
                or _decrypt(a.written_pin) != pin
                or a.written_schedule != desired
            ]
            others = others.filter(id__in=behind)
        flagged = sorted(others.values_list("lock_entity_id", flat=True))
        if flagged:
            others.update(
                reconcile_requested_at=now,
                push_state=DoorCode.PushState.PENDING,
                push_attempt_count=0,
                last_push_error=WAITING_ERROR,
            )
            transaction.on_commit(_wake_push_task, robust=True)
    return flagged


def rerequest_reconcile(*, door_code: DoorCode) -> list[str]:
    """Flag the code's locks still waiting for a reconcile again from now, for Retry. Returns them.

    So the queued push task picks them up as fresh, after Retry re-armed the
    ones the cap or a terminal failure stopped. The code row first.
    """
    from locks.use_cases.lock_push import _lock_code_row, _wake_push_task

    with transaction.atomic():
        _lock_code_row(door_code.id)
        waiting = DoorCodeLockAssignment.objects.filter(door_code=door_code, reconcile_requested_at__isnull=False)
        locks = sorted(waiting.values_list("lock_entity_id", flat=True))
        if locks:
            waiting.update(reconcile_requested_at=django_timezone.now())
            transaction.on_commit(_wake_push_task, robust=True)
    return locks


def run_reconciles_inline(*, door_code: DoorCode, lock_entity_ids: list[str], zwavejs, actor_user=None) -> None:
    """Reconcile these locks of the code now, each with its own push budget, where the push task doesn't run."""
    from locks.use_cases.lock_config_sync import LockBusy
    from locks.use_cases.lock_push import PUSH_LOCK_BUDGET_SECONDS, BudgetedGateway

    for lock_entity_id in lock_entity_ids:
        try:
            reconcile_added_lock(
                door_code_id=door_code.id,
                lock_entity_id=lock_entity_id,
                zwavejs=BudgetedGateway(zwavejs, seconds=PUSH_LOCK_BUDGET_SECONDS),
                actor_user=actor_user,
            )
        except LockBusy:
            logger.info("Reconcile of door code id=%d on %s is waiting for the lock", door_code.id, lock_entity_id)


def reconcile_due(*, now: datetime, max_attempts: int, fresh_only: bool):
    """Flagged locks to reconcile at ``now``, as a ``DoorCodeLockAssignment`` queryset.

    On a code that's active, started and not expired, not ``failed``, under the
    attempt cap and not being dropped. ``fresh_only`` is the queued push task's
    share, like a queued push: flagged within ``PUSH_REQUEST_TTL`` and not tried
    since. ``push_pending_door_codes`` retries the rest every 300s.
    """
    from locks.use_cases.lock_push import PUSH_REQUEST_TTL, being_removed_q

    pushable = DoorCode.objects.filter(is_active=True).filter(started_q(now) & ~expired_q(now))
    due = (
        DoorCodeLockAssignment.objects.filter(reconcile_requested_at__isnull=False, door_code__in=pushable)
        .exclude(push_state=DoorCode.PushState.FAILED)
        .exclude(being_removed_q())
    )
    if max_attempts > 0:
        due = due.filter(push_attempt_count__lt=max_attempts)
    if fresh_only:
        due = due.filter(reconcile_requested_at__gt=now - PUSH_REQUEST_TTL).filter(
            Q(last_push_attempt_at__isnull=True) | Q(last_push_attempt_at__lt=F("reconcile_requested_at"))
        )
    return due


def reconcile_added_lock(
    *,
    door_code_id: int,
    lock_entity_id: str,
    zwavejs,
    actor_user=None,
    timeout_seconds: float = 5.0,
    deadline: float | None = None,
) -> str:
    """Bring one flagged added lock in line with its code (module docstring). Returns the outcome.

    Waits for the lock's ``lock_sync:`` lock up to ``deadline`` (``LockBusy``
    past it) and has to run in autocommit, like a push. A run that worked but
    found the lock flagged again meanwhile (lock sync changed the code while it
    ran) goes again right away, up to :data:`_MAX_PASSES` times, so the change
    doesn't wait for the scheduler's next 300s retry.
    """
    from locks.use_cases.lock_config_sync import hold_lock_sync

    with hold_lock_sync([lock_entity_id], deadline=deadline):
        for _ in range(_MAX_PASSES):
            outcome = _reconcile_locked(
                door_code_id=door_code_id,
                lock_entity_id=lock_entity_id,
                zwavejs=zwavejs,
                actor_user=actor_user,
                timeout_seconds=timeout_seconds,
            )
            flagged_again = DoorCodeLockAssignment.objects.filter(
                door_code_id=door_code_id, lock_entity_id=lock_entity_id, reconcile_requested_at__isnull=False
            ).exists()
            if outcome not in (IN_LINE, PUSHED, HELD) or not flagged_again:
                return outcome
        return outcome


# How many times :func:`reconcile_added_lock` goes again for a lock flagged while it ran.
_MAX_PASSES = 3


def _reconcile_locked(*, door_code_id: int, lock_entity_id: str, zwavejs, actor_user, timeout_seconds: float) -> str:
    from locks.use_cases.lock_config_sync import InvalidRequest, NotFound, _resolve_lock_node_id
    from locks.use_cases.lock_push import (
        InvalidPin,
        LockPushFailed,
        LockSlotsFull,
        LockUnreachable,
        PushSuperseded,
        _locks_being_removed,
        _out_of_budget,
        decrypt_pin_or_none,
        refresh_push_state,
    )

    assignment = DoorCodeLockAssignment.objects.filter(door_code_id=door_code_id, lock_entity_id=lock_entity_id).first()
    code = DoorCode.objects.filter(id=door_code_id).first()
    if assignment is None or code is None or assignment.reconcile_requested_at is None:
        return NOTHING
    requested_at = assignment.reconcile_requested_at
    if not code.is_active or not belongs_on_lock(code) or lock_entity_id in _locks_being_removed(door_code=code):
        return WAITING
    pin = decrypt_pin_or_none(code)
    if not pin:
        _record_failure(code=code, assignment=assignment, message="No readable PIN to send.", terminal=True)
        return FAILED
    try:
        node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    except (NotFound, InvalidRequest) as exc:
        _record_failure(code=code, assignment=assignment, message=str(exc), terminal=True)
        return FAILED

    DoorCodeLockAssignment.objects.filter(id=assignment.id).update(last_push_attempt_at=django_timezone.now())
    try:
        outcome = _bring_in_line(
            code=code,
            assignment=assignment,
            pin=pin,
            node_id=node_id,
            zwavejs=zwavejs,
            actor_user=actor_user,
            timeout_seconds=timeout_seconds,
        )
    except _Transient as exc:
        _record_failure(
            code=code,
            assignment=assignment,
            message=str(exc),
            terminal=False,
            counted=not _out_of_budget(zwavejs),
        )
        return RETRY
    except PushSuperseded:
        # Off, out of its dates or dropped since; the next run sees why.
        return WAITING
    except (LockUnreachable, LockSlotsFull):
        # Recorded on the lock by the push.
        return RETRY
    except (LockPushFailed, InvalidPin):
        return FAILED
    # Only the flag this run read: a sync that flagged the lock again meanwhile gets another run.
    DoorCodeLockAssignment.objects.filter(id=assignment.id, reconcile_requested_at=requested_at).update(
        reconcile_requested_at=None
    )
    refresh_push_state(door_code=code)
    return outcome


def _bring_in_line(
    *,
    code: DoorCode,
    assignment: DoorCodeLockAssignment,
    pin: str,
    node_id: int,
    zwavejs,
    actor_user,
    timeout_seconds: float,
) -> str:
    from locks.use_cases.lock_push import _lock_code_row, code_schedule_fingerprint, push_door_code_to_lock

    lock_entity_id = assignment.lock_entity_id
    slot_index = assignment.slot_index
    _clear_stale_attempts(
        code=code,
        lock_entity_id=lock_entity_id,
        node_id=node_id,
        pin=pin,
        tracked=slot_index,
        zwavejs=zwavejs,
        timeout_seconds=timeout_seconds,
    )
    if slot_index is not None:
        written_pin = _decrypt(assignment.written_pin)
        holds = _read_tracked_slot(
            zwavejs=zwavejs,
            node_id=node_id,
            slot_index=int(slot_index),
            pin=pin,
            written_pin=written_pin,
            timeout_seconds=timeout_seconds,
        )
        if holds == _CURRENT:
            desired = code_schedule_fingerprint(code)
            written = assignment.written_schedule
            if written == desired:
                with transaction.atomic():
                    _lock_code_row(code.id)
                    DoorCodeLockAssignment.objects.filter(id=assignment.id).update(
                        push_state=DoorCode.PushState.PUSHED,
                        push_attempt_count=0,
                        last_push_error="",
                        schedule_pending=False,
                        written_pin=SettingsEncryption.get().encrypt(pin),
                        written_schedule=desired,
                    )
                return IN_LINE
            if written is not None and schedule_only_grows(old_days=_days_of(written), new_days=code.days_of_week):
                # Every day it had stays, so sending the schedule overwrites it all.
                # Not known what's there (a row from before 0012, or a schedule
                # push that didn't finish): cleared and pushed again below.
                with transaction.atomic():
                    _lock_code_row(code.id)
                    DoorCodeLockAssignment.objects.filter(id=assignment.id).update(
                        push_state=DoorCode.PushState.PENDING,
                        schedule_pending=True,
                        written_pin=SettingsEncryption.get().encrypt(pin),
                    )
                push_door_code_to_lock(
                    door_code=code,
                    lock_entity_id=lock_entity_id,
                    zwavejs=zwavejs,
                    actor_user=actor_user,
                    timeout_seconds=timeout_seconds,
                )
                return PUSHED
            # A day goes away, or what's there isn't known: clear the slot and push it fresh.
            _clear_tracked_slot(code=code, assignment=assignment, zwavejs=zwavejs, timeout_seconds=timeout_seconds)
        elif holds == _STALE:
            _clear_tracked_slot(code=code, assignment=assignment, zwavejs=zwavejs, timeout_seconds=timeout_seconds)
        else:
            _let_go(code=code, assignment=assignment, empty=holds == _EMPTY)

    held = pin_held_by_another_code(door_code=code, lock_entity_id=lock_entity_id, pin=pin)
    if held is not None:
        with transaction.atomic():
            _lock_code_row(code.id)
            DoorCodeLockAssignment.objects.filter(id=assignment.id).update(
                push_state=DoorCode.PushState.FAILED, push_attempt_count=0, last_push_error=held_pin_error(held)
            )
        return HELD
    push_door_code_to_lock(
        door_code=code,
        lock_entity_id=lock_entity_id,
        zwavejs=zwavejs,
        actor_user=actor_user,
        timeout_seconds=timeout_seconds,
    )
    return PUSHED


def _decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return SettingsEncryption.get().decrypt(token)
    except Exception:
        return None


def read_added_slot(
    *, zwavejs, node_id: int, slot_index: int, pin: str | None, written_pin: str | None, timeout_seconds: float
) -> str:
    """:func:`_read_tracked_slot`'s verdict, ``"current"``, ``"stale"``, ``"other"`` or ``"empty"``, for delete."""
    return _read_tracked_slot(
        zwavejs=zwavejs,
        node_id=node_id,
        slot_index=slot_index,
        pin=pin,
        written_pin=written_pin,
        timeout_seconds=timeout_seconds,
    )


def slot_is_latchpoints(verdict: str) -> bool:
    """Whether a :func:`read_added_slot` verdict is a PIN latchpoint put there, ie one a delete clears."""
    return verdict in (_CURRENT, _STALE)


def _read_tracked_slot(
    *, zwavejs, node_id: int, slot_index: int, pin: str | None, written_pin: str | None, timeout_seconds: float
) -> str:
    """Read the tracked slot live and say what it holds against ``pin`` (the code's) and ``written_pin``.

    A code the lock won't show is the one latchpoint wrote, since it pushed this
    slot: current when that was the code's PIN, stale otherwise or when what it
    wrote isn't known. A readable PIN that's neither is someone else's, but only
    when a push recorded what it wrote there. A slot pushed before migration
    0012 has nothing recorded (``written_pin`` is ``None``), and it may have
    fallen behind more than one change, so any readable PIN in it but the
    code's is taken as latchpoint's older one, like every clear did before.
    Raises :class:`_Transient` when the lock gives no usable answer.
    """
    from locks.use_cases.lock_config_sync import _coerce_int
    from locks.use_cases.lock_push import (
        _USER_ID_STATUS_CONFIG_USES,
        LockCodeUnverified,
        LockRejectedCode,
        _refresh_user_code_slot,
        _verify_user_code_slot,
    )

    def masked() -> str:
        return _CURRENT if written_pin and written_pin == pin else _STALE

    def config_slot() -> bool:
        response = _refresh_user_code_slot(
            zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, timeout_seconds=timeout_seconds
        )
        if isinstance(response, dict) and "response" in response:
            response = response["response"]
        status = response.get("userIdStatus") if isinstance(response, dict) else None
        return _coerce_int(status) in _USER_ID_STATUS_CONFIG_USES

    def holds(candidate: str) -> bool:
        try:
            return _verify_user_code_slot(
                zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, pin=candidate, timeout_seconds=timeout_seconds
            )
        except LockRejectedCode as exc:
            return bool(exc.holds_pin)

    try:
        try:
            exact = _verify_user_code_slot(
                zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, pin=pin or "", timeout_seconds=timeout_seconds
            )
        except LockRejectedCode as exc:
            if exc.holds_pin:
                # The code's PIN, disabled at the lock: still the code's slot (#219 flags it).
                return _CURRENT
            if exc.clear_slot:
                return _EMPTY
            if exc.holds_other:
                if written_pin is None:
                    # Nothing recorded: latchpoint's, as before 0012 (review of PR #223),
                    # unless it's lock config (messaging or passage mode), which never is.
                    return _OTHER if config_slot() else _STALE
                if written_pin != pin and holds(written_pin):
                    return _STALE
                return _OTHER
            # Disabled with a code the lock won't show.
            return masked()
        return _CURRENT if exact else masked()
    except (LockCodeUnverified, GatewayError) as exc:
        raise _Transient(f"Couldn't read slot {slot_index} back: {exc.__class__.__name__}") from exc


def _clear_tracked_slot(*, code: DoorCode, assignment: DoorCodeLockAssignment, zwavejs, timeout_seconds: float) -> None:
    """Clear the slot latchpoint's older PIN or schedule is in, then stop tracking it."""
    from locks.use_cases.lock_config_sync import clear_lock_user_code_slot

    slot_index = int(assignment.slot_index)
    try:
        clear_lock_user_code_slot(
            lock_entity_id=assignment.lock_entity_id,
            slot_index=slot_index,
            zwavejs=zwavejs,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        raise _Transient(f"Couldn't clear slot {slot_index}: {exc.__class__.__name__}") from exc
    _forget(code=code, assignment=assignment, outcome="cleared", slot_empty=False)


def _let_go(*, code: DoorCode, assignment: DoorCodeLockAssignment, empty: bool) -> None:
    """Stop tracking a slot that holds someone else's PIN or nothing, without touching it."""
    logger.info(
        "Slot %s on %s for door code id=%d holds %s; letting it go",
        assignment.slot_index,
        assignment.lock_entity_id,
        code.id,
        "nothing" if empty else "another PIN",
    )
    _forget(code=code, assignment=assignment, outcome="not_holding_pin", slot_empty=empty)


def _forget(*, code: DoorCode, assignment: DoorCodeLockAssignment, outcome: str, slot_empty: bool) -> None:
    from locks.use_cases.lock_push import _lock_code_row, _settle_unconfirmed_slot

    slot_index = int(assignment.slot_index)
    with transaction.atomic():
        _lock_code_row(code.id)
        _settle_unconfirmed_slot(
            door_code=code,
            lock_entity_id=assignment.lock_entity_id,
            slot_index=slot_index,
            outcome=outcome,
            slot_empty=slot_empty,
        )
        DoorCodeLockAssignment.objects.filter(id=assignment.id).update(
            slot_index=None,
            written_pin=None,
            written_schedule=None,
            schedule_pending=False,
            push_state=DoorCode.PushState.PENDING,
        )
    assignment.slot_index = None


def _clear_stale_attempts(
    *,
    code: DoorCode,
    lock_entity_id: str,
    node_id: int,
    pin: str,
    tracked: int | None,
    zwavejs,
    timeout_seconds: float,
) -> None:
    """Clear slots an unconfirmed push left an older PIN of the code in, before anything is pushed.

    An attempt holding the code's current PIN is left for the push to adopt,
    and one recorded without its PIN can't be compared, so it's left to the
    cleanups that handle those. The rest are read back and cleared when they
    still hold the PIN that attempt sent (or a masked code, for a tagged
    attempt), and settled either way. Has to run before the push, whose
    ``code_synced`` event ends the attempts' window.
    """
    from locks.use_cases.lock_config_sync import clear_lock_user_code_slot
    from locks.use_cases.lock_push import (
        _HOLDS_OURS,
        _READ_BACK_EMPTY,
        _available_attempt_slots,
        _claimed_slots,
        _read_back_attempt_slot,
        _settle_unconfirmed_slot,
        _unconfirmed_attempts,
        _verified_attempt_slots,
    )

    attempts = _unconfirmed_attempts(
        door_code=code,
        lock_entity_id=lock_entity_id,
        claimed_slots=_claimed_slots(lock_entity_id=lock_entity_id, door_code=code),
    )
    stale = {slot: sent for slot, sent in attempts.items() if slot != tracked and sent and sent != pin}
    if not stale:
        return
    verified = _verified_attempt_slots(door_code=code, lock_entity_id=lock_entity_id)
    available = _available_attempt_slots(door_code=code, lock_entity_id=lock_entity_id)
    for slot_index, sent in stale.items():
        try:
            verdict = _read_back_attempt_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                pin=sent,
                timeout_seconds=timeout_seconds,
                masked_counts=slot_index in verified or slot_index in available,
                disabled_masked_counts=slot_index in verified,
            )
            if verdict == _HOLDS_OURS:
                clear_lock_user_code_slot(
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    zwavejs=zwavejs,
                    timeout_seconds=timeout_seconds,
                )
        except Exception as exc:
            raise _Transient(f"Couldn't check slot {slot_index}: {exc.__class__.__name__}") from exc
        _settle_unconfirmed_slot(
            door_code=code,
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            outcome="cleared" if verdict == _HOLDS_OURS else "not_holding_pin",
            slot_empty=verdict == _READ_BACK_EMPTY,
        )


def _record_failure(
    *, code: DoorCode, assignment: DoorCodeLockAssignment, message: str, terminal: bool, counted: bool = True
) -> None:
    """Count a failed reconcile on the lock; the flag stays, so the scheduler tries it again under the cap.

    Not ``counted`` when it ran out of its time budget, like a push (issue #124).
    """
    from locks.use_cases.lock_push import (
        _cut_push_error,
        _lock_code_row,
        _push_max_attempts,
        refresh_push_state,
        sanitize_push_error_for_storage,
    )

    logger.warning("Reconciling door code id=%d on %s: %s", code.id, assignment.lock_entity_id, message)
    max_attempts = _push_max_attempts()
    with transaction.atomic():
        _lock_code_row(code.id)
        row = DoorCodeLockAssignment.objects.filter(id=assignment.id).first()
        if row is None:
            return
        attempts = row.push_attempt_count + (1 if counted else 0)
        capped = max_attempts > 0 and attempts >= max_attempts
        DoorCodeLockAssignment.objects.filter(id=assignment.id).update(
            push_state=DoorCode.PushState.FAILED if terminal or capped else DoorCode.PushState.PENDING,
            push_attempt_count=attempts,
            last_push_error=_cut_push_error(sanitize_push_error_for_storage(message)),
            last_push_attempt_at=django_timezone.now(),
        )
        refresh_push_state(door_code=code)
