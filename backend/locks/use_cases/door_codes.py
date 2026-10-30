from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone as django_timezone

from accounts.models import User
from accounts.policies import is_admin
from alarm.crypto import SettingsEncryption
from config.domain_exceptions import ConflictError, ForbiddenError, GatewayError, NotFoundError, ValidationError
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases.code_lifecycle import is_expired, is_started, starts_by

logger = logging.getLogger(__name__)

# The CC 99 clear timeout for the clears an update or delete runs while the request
# waits, the 5s the push and the shared clear helpers use, not the gateway's 10s
# default (issue #124).
_REQUEST_CLEAR_TIMEOUT_SECONDS = 5.0

# How long Retry's clear retries may take in the request, lock waits included.
# Room for one unconfirmed slot's readback and clear on a slow lock (issue #124).
_RETRY_CLEAR_BUDGET_SECONDS = 15.0

if TYPE_CHECKING:
    from alarm.gateways.zwavejs import ZwavejsGateway
    from locks.use_cases.lock_push import ClearFailure


class Forbidden(ForbiddenError):
    pass


class NotFound(NotFoundError):
    pass


class ReauthRequired(ValidationError):
    pass


class ReauthFailed(ForbiddenError):
    pass


class DoorCodeInactive(ConflictError):
    pass


class DoorCodeNotStarted(ConflictError):
    """Retry on an active code before its ``start_at``: it isn't pushed until then (issue #145)."""


class SlotClearFailed(GatewayError):
    """A slot that may hold the code's PIN couldn't be cleared, so the code was kept."""

    gateway_name = "zwavejs"


def assert_admin(*, user: User) -> None:
    """Raise `Forbidden` if `user` is not an admin."""
    if not is_admin(user):
        raise Forbidden("Forbidden.")


def assert_admin_reauth(*, user: User, reauth_password: str | None) -> None:
    """Validate admin re-auth password; raise `ReauthRequired`/`ReauthFailed` on failure."""
    if not reauth_password:
        raise ReauthRequired("Re-authentication required.")
    if not user.check_password(reauth_password):
        raise ReauthFailed("Re-authentication failed.")


def resolve_list_target_user(*, actor_user: User, requested_user_id: str | None) -> User:
    """Resolve which user's door codes are being listed, enforcing admin-only access to others."""
    if requested_user_id and is_admin(actor_user):
        target_user = User.objects.filter(id=requested_user_id).first()
        if not target_user:
            raise NotFound("User not found.")
        return target_user
    return actor_user


def resolve_create_target_user(*, actor_user: User, requested_user_id: str | None) -> User:
    """Resolve which user a new door code should be created for (admin-only)."""
    assert_admin(user=actor_user)
    target_user_id = requested_user_id or str(actor_user.id)
    target_user = User.objects.filter(id=target_user_id).first()
    if not target_user:
        raise NotFound("User not found.")
    return target_user


def list_door_codes_for_user(*, user: User) -> QuerySet[DoorCode]:
    """Return a queryset of `DoorCode` rows for `user`, with common relations prefetched."""
    has_active_assignment = Exists(DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk")))
    return (
        DoorCode.objects.select_related("user")
        .prefetch_related("lock_assignments")
        .filter(user=user)
        .annotate(_has_active_assignment=has_active_assignment)
        .filter(Q(source=DoorCode.Source.MANUAL) | Q(_has_active_assignment=True))
        .order_by("-created_at")
    )


def get_door_code_for_read(*, code_id: int) -> DoorCode:
    """Fetch a door code by id (with relations) or raise `NotFound`."""
    code = DoorCode.objects.select_related("user").prefetch_related("lock_assignments").filter(id=code_id).first()
    if not code:
        raise NotFound("Not found.")
    return code


def get_door_code_for_admin_update(*, actor_user: User, code_id: int) -> DoorCode:
    """Fetch a door code for admin update, enforcing admin permissions and raising `NotFound`."""
    assert_admin(user=actor_user)
    code = DoorCode.objects.select_related("user").prefetch_related("lock_assignments").filter(id=code_id).first()
    if not code:
        raise NotFound("Not found.")
    return code


def create_door_code(
    *,
    user: User,
    raw_code: str,
    label: str = "",
    code_type: str = DoorCode.CodeType.PERMANENT,
    start_at=None,
    end_at=None,
    days_of_week: int | None = None,
    window_start=None,
    window_end=None,
    max_uses: int | None = None,
    lock_entity_ids: list[str] | None = None,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
) -> DoorCode:
    """Create a door code, assign it to locks (optional), push to each lock, and emit events."""
    raw_code = (raw_code or "").strip()
    code = DoorCode.objects.create(
        user=user,
        encrypted_pin=SettingsEncryption.get().encrypt(raw_code),
        label=label or "",
        code_type=code_type,
        pin_length=len(raw_code),
        is_active=True,
        start_at=start_at,
        end_at=end_at,
        days_of_week=days_of_week,
        window_start=window_start,
        window_end=window_end,
        max_uses=max_uses,
    )

    if lock_entity_ids:
        DoorCodeLockAssignment.objects.bulk_create(
            [
                DoorCodeLockAssignment(
                    door_code=code,
                    lock_entity_id=entity_id,
                )
                for entity_id in lock_entity_ids
            ],
            ignore_conflicts=True,
        )

    DoorCodeEvent.objects.create(
        door_code=code,
        user=actor_user or user,
        event_type=DoorCodeEvent.EventType.CODE_CREATED,
        metadata={"label": code.label, "code_type": code.code_type},
    )

    if zwavejs is not None and lock_entity_ids:
        from locks.use_cases.lock_push import push_task_running

        if push_task_running():
            # Saved and returned pending; the scheduler pushes it in seconds (issue #124).
            _request_push_best_effort(code=code, actor_user=actor_user)
        else:
            # Refresh so the freshly-created assignments are visible to push.
            code = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
            _push_to_assigned_locks_best_effort(code=code, zwavejs=zwavejs, actor_user=actor_user)

    return code


# Fields whose change requires re-pushing the code onto the physical lock.
# ``start_at`` / ``end_at`` are never programmed onto the lock. The PIN is only
# on a lock between them (ADR 0109), so ``start_at`` crossing now is a derived
# trigger below, and ``enforce_door_code_validity`` handles the clock passing them.
_PUSH_TRIGGER_FIELDS = frozenset({"code", "is_active", "days_of_week", "window_start", "window_end"})


def _changed_push_trigger_fields(*, code: DoorCode, changes: dict, old_pin: str | None) -> set[str]:
    """Return the push trigger fields in ``changes`` whose value differs from ``code``'s.

    The edit form only sends the fields that were edited (#155), but it always
    sends ``is_active: false`` for an inactive code, and other API clients may
    send unchanged values, so a key being present doesn't mean it changed
    (issue #139). Call before ``changes`` is applied.

    ``start_at`` counts when the new value moves the start across now, ie a
    code on its locks gets a start in the future (it comes off them) or one
    waiting for its start gets one in the past (it goes on). Moving it within
    the past or within the future doesn't touch the locks (issue #145).
    """
    from locks.use_cases.lock_push import has_unconfirmed_attempt_slots

    changed: set[str] = set()
    if "start_at" in changes:
        now = django_timezone.now()
        if starts_by(changes.get("start_at"), now=now) != is_started(code, now=now):
            changed.add("start_at")
    for field in _PUSH_TRIGGER_FIELDS & changes.keys():
        new = changes.get(field)
        if field == "code":
            # Encrypted at rest, so compare plaintext. An empty code isn't applied.
            if new and str(new).strip() != old_pin:
                changed.add(field)
        elif field == "is_active":
            # Sending false for a code that's already inactive but may still have its
            # PIN on a lock (a tracked slot, or a slot only an unconfirmed push
            # attempt knows about) still clears it, like before.
            if bool(new) != code.is_active or (
                not new
                and (
                    DoorCodeLockAssignment.objects.filter(door_code=code, slot_index__isnull=False).exists()
                    or has_unconfirmed_attempt_slots(door_code=code)
                )
            ):
                changed.add(field)
        elif new != getattr(code, field):
            changed.add(field)
    return changed


@contextlib.contextmanager
def _hold_door_code_locks(*, code: DoorCode, extra_lock_entity_ids=()):
    """Hold ``lock_sync:`` for every lock an update or delete of ``code`` may touch (issue #131).

    Waits for each lock (bounded, :class:`LockBusy` past it) in sorted order.
    Once they're held the set is worked out again, and if it grew meanwhile (a
    concurrent save added a lock) they're released and taken again with the
    extra ones, so the order stays sorted. Pushes nested inside stack on these.
    Every wait, retakes included, shares one deadline so the whole request waits
    at most :data:`SYNC_LOCK_WAIT_SECONDS`.
    Re-reads ``code`` from the DB once held, raising :class:`NotFound` if it's gone.
    """
    from locks.use_cases.lock_config_sync import hold_lock_sync, sync_lock_deadline
    from locks.use_cases.lock_push import affected_lock_entity_ids

    deadline = sync_lock_deadline()
    extra = set(extra_lock_entity_ids or ())
    wanted = extra | affected_lock_entity_ids(door_code=code)
    while True:
        with hold_lock_sync(wanted, deadline=deadline):
            needed = extra | affected_lock_entity_ids(door_code=code)
            if needed <= wanted:
                try:
                    code.refresh_from_db()
                except DoorCode.DoesNotExist as exc:
                    raise NotFound("Not found.") from exc
                yield
                return
        wanted |= needed


def update_door_code(
    *,
    code: DoorCode,
    changes: dict,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
) -> DoorCode:
    """Update a door code while holding the ``lock_sync:`` lock of every lock it touches (issue #131).

    Waits for a push or config sync already running on one of those locks, and
    raises :class:`LockBusy` (409) without changing anything when one is still
    running at the wait limit. See :func:`_update_door_code_locked`.

    Its push isn't made while those locks are held (issue #124): it's queued
    for the scheduler, or where that doesn't run in this process it goes out
    inline once they're let go, each lock's push still taking its own
    ``lock_sync:`` lock and reading the code again.
    """
    with _hold_door_code_locks(code=code, extra_lock_entity_ids=changes.get("lock_entity_ids") or ()):
        code, push_inline = _update_door_code_locked(code=code, changes=changes, actor_user=actor_user, zwavejs=zwavejs)
    if push_inline and zwavejs is not None:
        fresh = DoorCode.objects.prefetch_related("lock_assignments").filter(id=code.id).first()
        if fresh is not None:
            _push_to_assigned_locks_best_effort(code=fresh, zwavejs=zwavejs, actor_user=actor_user)
            code = fresh
    return code


def retire_door_code(
    *,
    code: DoorCode,
    reason: str,
    zwavejs: ZwavejsGateway,
    now=None,
) -> DoorCode | None:
    """Turn off a code that's past its ``end_at`` and take it off its locks (issue #145).

    Holds the ``lock_sync:`` locks like an update (:func:`_hold_door_code_locks`),
    then checks the row it read again once they're held: a code turned off,
    given a later ``end_at`` or deleted while this waited is left alone. Anything
    else goes through the same locked update a user's deactivate does, so its
    tracked and unconfirmed slots get cleared and a clear that fails is recorded
    for the scheduler's retries, attempt cap and #167 inactive clear. ``reason``
    goes in the ``code_updated`` event. Returns the code, or ``None`` when it
    was left alone. Raises :class:`LockBusy` like an update.
    """
    try:
        with _hold_door_code_locks(code=code):
            check_at = now if now is not None else django_timezone.now()
            if not code.is_active or not is_expired(code, now=check_at):
                return None
            # A deactivate, so there's never a push to make afterwards.
            code, _push_inline = _update_door_code_locked(
                code=code,
                changes={"is_active": False},
                actor_user=None,
                zwavejs=zwavejs,
                event_metadata={"reason": reason},
            )
            return code
    except NotFound:
        return None


def withdraw_door_code(*, code: DoorCode, zwavejs: ZwavejsGateway, now=None) -> bool:
    """Clear an active code's PIN off its locks before its ``start_at``, leaving it active (issue #145).

    For codes pushed before their start, ie before this was enforced or when the
    start was moved later through the API. Holds the ``lock_sync:`` locks like
    an update and checks again once they're held, so a code that started, was
    turned off or was deleted meanwhile is left alone. Tracked slots are read
    back and cleared unless they hold someone else's code (issue #186), and
    unconfirmed slots are read back and cleared when they hold its PIN
    (:func:`withdraw_slots_before_start`). A clear that fails
    is recorded like any other, so the scheduler retries it, and slots that
    already have one are left to that retry. ``enforce_door_code_validity``
    pushes the code again once it starts. Returns whether anything was tried.
    Raises :class:`LockBusy` like an update.

    Checked once before the locks are taken too, so a code with nothing left to
    withdraw (its slots already cleared or left to the clear retries) doesn't
    hold every lock it's on each tick and make a push there wait (PR #183 review).
    """
    from locks.use_cases.lock_push import (
        refresh_push_state,
        slots_to_withdraw,
        withdraw_slots_before_start,
    )

    def nothing_to_withdraw() -> bool:
        check_at = now if now is not None else django_timezone.now()
        return not code.is_active or is_started(code, now=check_at) or not slots_to_withdraw(door_code=code)

    if nothing_to_withdraw():
        return False
    try:
        with _hold_door_code_locks(code=code):
            if nothing_to_withdraw():
                return False
            cleared, failures = withdraw_slots_before_start(door_code=code, zwavejs=zwavejs)
            # Off its locks until it starts, so it's pending (scheduled), or
            # failed once its clears hit the cap (issue #126). Each lock it
            # cleared went back to pending through forget_cleared_slot.
            refresh_push_state(door_code=code)
            DoorCodeEvent.objects.create(
                door_code=code,
                user=None,
                event_type=DoorCodeEvent.EventType.CODE_REMOVED,
                metadata={
                    "action": "withdrawn",
                    "reason": "not_started",
                    "cleared_slots": cleared,
                    **({"failed_slot_clears": [f.as_metadata() for f in failures]} if failures else {}),
                },
            )
            return True
    except NotFound:
        return False


def _update_door_code_locked(
    *,
    code: DoorCode,
    changes: dict,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
    event_metadata: dict[str, object] | None = None,
) -> tuple[DoorCode, bool]:
    """Update a door code and its lock assignments, emitting a `DoorCodeEvent` when changed.

    Returns the code and whether the caller still has to push it inline, once
    it lets go of the ``lock_sync:`` locks (issue #124). When the scheduler's
    push task runs in this process the push is queued here instead
    (:func:`locks.use_cases.lock_push.request_push`) and that's ``False``.

    When ``zwavejs`` is provided, dropped locks' slots are CC 99 ``clear``-ed. A
    change to a push-relevant field's value clears and re-pushes every lock; a
    lock-list-only change keeps the surviving locks' slots and pushes only locks
    without one. An inactive code is never pushed, and neither is one outside
    its ``start_at``/``end_at`` (issue #145). A slot whose clear fails
    transiently stays tracked (a dropped lock keeps its assignment), is recorded
    per lock for the scheduler and Retry to clear later, and keeps the code from
    showing ``pushed``. A lock latchpoint can't resolve to a Z-Wave node any more
    is dropped or forgotten anyway, since no clear can reach it.
    ``event_metadata`` is added to the ``code_updated`` event.
    """
    updated_fields = []
    push_inline = False

    # Snapshot the PIN before it can be overwritten: a still-pending push may have
    # left it in a slot that only the recorded unconfirmed attempts know about.
    old_pin: str | None = None
    push_trigger_changes: set[str] = set()
    if zwavejs is not None:
        from locks.use_cases.lock_config_sync import clear_lock_user_code_slot
        from locks.use_cases.lock_push import (
            cancel_pending_removal,
            clear_unconfirmed_slots_holding_pin,
            decrypt_pin_or_none,
            forget_cleared_slot,
            record_clear_failure,
            refresh_push_state,
            resolve_clear_failure,
        )

        old_pin = decrypt_pin_or_none(code)
        push_trigger_changes = _changed_push_trigger_fields(code=code, changes=changes, old_pin=old_pin)

    if "code" in changes and changes.get("code"):
        raw_code = str(changes.get("code") or "").strip()
        code.encrypted_pin = SettingsEncryption.get().encrypt(raw_code)
        code.pin_length = len(raw_code)
        updated_fields.append("code")

    if "label" in changes:
        code.label = changes.get("label") or ""
        updated_fields.append("label")

    if "is_active" in changes:
        code.is_active = bool(changes.get("is_active"))
        updated_fields.append("is_active")

    if "max_uses" in changes:
        code.max_uses = changes.get("max_uses")
        updated_fields.append("max_uses")

    time_keys = {"start_at", "end_at", "days_of_week", "window_start", "window_end"}
    if any(key in changes for key in time_keys):
        if "start_at" in changes:
            code.start_at = changes.get("start_at")
            updated_fields.append("start_at")
        if "end_at" in changes:
            code.end_at = changes.get("end_at")
            updated_fields.append("end_at")
        if "days_of_week" in changes:
            code.days_of_week = changes.get("days_of_week")
            updated_fields.append("days_of_week")
        if "window_start" in changes:
            code.window_start = changes.get("window_start")
            updated_fields.append("window_start")
        if "window_end" in changes:
            code.window_end = changes.get("window_end")
            updated_fields.append("window_end")

    code.save()

    # Diff the lock set. Locks that stay keep their assignment and slot_index;
    # recreating them would forget a slot the lock still holds the PIN in, and the
    # re-push would write it into a second slot (issue #133).
    dropped_lock_entity_ids: list[str] = []
    removed_lock_entity_ids: list[str] = []
    added_lock_entity_ids: list[str] = []
    failed_slot_clears: list[ClearFailure] = []
    if "lock_entity_ids" in changes:
        new_entity_ids = list(dict.fromkeys(changes.get("lock_entity_ids") or []))
        old_assignments = list(DoorCodeLockAssignment.objects.filter(door_code=code))
        old_entity_ids = {assignment.lock_entity_id for assignment in old_assignments}
        removed_assignment_ids: list[int] = []
        for assignment in old_assignments:
            if assignment.lock_entity_id in new_entity_ids:
                if zwavejs is not None:
                    # Kept (or re-added) while an earlier drop's clear was still
                    # failing: the lock stays on the code once that clear works.
                    cancel_pending_removal(door_code=code, lock_entity_id=assignment.lock_entity_id)
                continue
            dropped_lock_entity_ids.append(assignment.lock_entity_id)
            if zwavejs is not None and assignment.slot_index is not None:
                slot_index = int(assignment.slot_index)
                try:
                    clear_lock_user_code_slot(
                        lock_entity_id=assignment.lock_entity_id,
                        slot_index=slot_index,
                        zwavejs=zwavejs,
                        timeout_seconds=_REQUEST_CLEAR_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    failure = record_clear_failure(
                        door_code=code,
                        lock_entity_id=assignment.lock_entity_id,
                        slot_index=slot_index,
                        exc=exc,
                        expected_pin=old_pin,
                        removing=True,
                    )
                    failed_slot_clears.append(failure)
                    if not failure.permanent:
                        # An offline lock doesn't fail the PATCH, but its assignment
                        # and slot stay until a clear works, so the PIN isn't left on
                        # the lock with nothing tracking it (issue #139).
                        continue
                else:
                    resolve_clear_failure(
                        door_code=code,
                        lock_entity_id=assignment.lock_entity_id,
                        slot_index=slot_index,
                        outcome="cleared",
                    )
            removed_assignment_ids.append(assignment.id)
            removed_lock_entity_ids.append(assignment.lock_entity_id)
        added_lock_entity_ids = [entity_id for entity_id in new_entity_ids if entity_id not in old_entity_ids]

        if removed_assignment_ids:
            DoorCodeLockAssignment.objects.filter(id__in=removed_assignment_ids).delete()

        if added_lock_entity_ids:
            DoorCodeLockAssignment.objects.bulk_create(
                [
                    DoorCodeLockAssignment(
                        door_code=code,
                        lock_entity_id=entity_id,
                    )
                    for entity_id in added_lock_entity_ids
                ],
                ignore_conflicts=True,
            )
        updated_fields.append("lock_entity_ids")

    updated_event: DoorCodeEvent | None = None
    if updated_fields:
        metadata: dict[str, object] = {"updated_fields": updated_fields, **(event_metadata or {})}
        if added_lock_entity_ids:
            metadata["added_lock_entity_ids"] = sorted(added_lock_entity_ids)
        if removed_lock_entity_ids:
            metadata["removed_lock_entity_ids"] = sorted(removed_lock_entity_ids)
        updated_event = DoorCodeEvent.objects.create(
            door_code=code,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_UPDATED,
            metadata=metadata,
        )

    if zwavejs is not None:
        # A pending code's PIN may sit in a slot recorded only as an unconfirmed
        # attempt. Clear it where the code no longer belongs there with that PIN:
        # dropped locks always, surviving locks when the PIN changes, the code is
        # deactivated or its start moves into the future. (A schedule-only change
        # re-pushes and adopts it instead.)
        deactivating = "is_active" in push_trigger_changes and not code.is_active
        withdrawing = "start_at" in push_trigger_changes and code.is_active and not is_started(code)
        unconfirmed_lock_ids = list(dropped_lock_entity_ids)
        if "code" in push_trigger_changes or deactivating or withdrawing:
            unconfirmed_lock_ids.extend(
                DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", flat=True)
            )
        if old_pin and unconfirmed_lock_ids:
            _, unconfirmed_failures = clear_unconfirmed_slots_holding_pin(
                door_code=code,
                pin=old_pin,
                lock_entity_ids=unconfirmed_lock_ids,
                zwavejs=zwavejs,
            )
            failed_slot_clears.extend(unconfirmed_failures)

        push_relevant_change = bool(push_trigger_changes)
        if push_relevant_change or "lock_entity_ids" in changes:
            if push_relevant_change:
                # PIN, schedule, or is_active changed. The lock still holds the OLD
                # PIN at the OLD slot; pushing fresh would pick a *different* slot
                # and strand the old PIN — breaking the ADR's "Created in the UI =
                # works on the door" guarantee. Clear the existing programmed slots
                # before the re-push runs. A lock dropped in this save whose clear
                # just failed keeps its slot and isn't tried again here.
                existing_pushed = DoorCodeLockAssignment.objects.filter(
                    door_code=code, slot_index__isnull=False
                ).exclude(lock_entity_id__in=dropped_lock_entity_ids)
                for assignment in existing_pushed:
                    slot_index = int(assignment.slot_index)
                    try:
                        clear_lock_user_code_slot(
                            lock_entity_id=assignment.lock_entity_id,
                            slot_index=slot_index,
                            zwavejs=zwavejs,
                            timeout_seconds=_REQUEST_CLEAR_TIMEOUT_SECONDS,
                        )
                    except Exception as exc:
                        failure = record_clear_failure(
                            door_code=code,
                            lock_entity_id=assignment.lock_entity_id,
                            slot_index=slot_index,
                            exc=exc,
                            expected_pin=old_pin,
                        )
                        failed_slot_clears.append(failure)
                        if not failure.permanent:
                            # Keep the slot. Forgetting it would leave the old PIN on
                            # the lock untracked (issue #139), and the re-push skips it.
                            continue
                        outcome = "lock_missing"
                    else:
                        outcome = "cleared"
                    # The re-push treats this lock as unassigned, and a lock an earlier
                    # save was still trying to drop goes now.
                    forget_cleared_slot(
                        door_code=code,
                        lock_entity_id=assignment.lock_entity_id,
                        slot_index=slot_index,
                        outcome=outcome,
                    )
                with transaction.atomic():
                    # The code row before its assignment rows, like every writer of both.
                    DoorCode.objects.select_for_update().filter(id=code.id).first()
                    # A fresh start for the clear-retry cap (issue #126).
                    code.push_attempt_count = 0
                    DoorCode.objects.filter(id=code.id).update(push_attempt_count=0)
                    # Every kept lock without a slot now needs a fresh push (issue
                    # #126). One whose clear failed keeps its slot and its state.
                    DoorCodeLockAssignment.objects.filter(door_code=code, slot_index__isnull=True).exclude(
                        lock_entity_id__in=dropped_lock_entity_ids
                    ).update(
                        push_state=DoorCode.PushState.PENDING,
                        push_attempt_count=0,
                        last_push_error="",
                        schedule_pending=False,
                    )
                    refresh_push_state(door_code=code)

            if not code.is_active:
                # An inactive code is never pushed (issue #138).
                if push_relevant_change:
                    # Deactivation (or a change to an inactive code): the lock holds
                    # no programmed slots for this code anymore, so stop here.
                    code.last_push_attempt_at = django_timezone.now()
                    DoorCode.objects.filter(id=code.id).update(
                        last_push_attempt_at=code.last_push_attempt_at, updated_at=code.last_push_attempt_at
                    )
            else:
                from locks.use_cases.lock_push import push_task_running

                # Not under the locks this holds, so a slow lock doesn't keep the
                # others busy for the whole push (issue #124).
                if push_task_running():
                    _request_push_best_effort(code=code, actor_user=actor_user)
                else:
                    push_inline = True

        if failed_slot_clears and updated_event is not None:
            updated_event.metadata["failed_slot_clears"] = [f.as_metadata() for f in failed_slot_clears]
            updated_event.save(update_fields=["metadata"])

    # Last, from what the clears and pushes above left (issue #126). That covers
    # a code left with no locks (issue #142), a failure left by a dropped lock,
    # and a lock that may still hold the PIN keeping the code from pushed (#144).
    if zwavejs is not None or "lock_entity_ids" in changes:
        from locks.use_cases.lock_push import refresh_push_state

        refresh_push_state(door_code=code)

    return code, push_inline


def delete_door_code(
    *,
    code: DoorCode,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
) -> None:
    """Delete a door code while holding the ``lock_sync:`` lock of every lock it touches (issue #131).

    Waits for a push or config sync already running on one of those locks, so
    a push that lands while the delete waits is in the slots it clears, and
    raises :class:`LockBusy` (409) without touching the code when one is still
    running at the wait limit. See :func:`_delete_door_code_locked`.
    """
    with _hold_door_code_locks(code=code):
        _delete_door_code_locked(code=code, actor_user=actor_user, zwavejs=zwavejs)


def _delete_door_code_locked(
    *,
    code: DoorCode,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
) -> None:
    """Delete a door code and emit a `DoorCodeEvent` capturing who deleted it.

    Synced codes (ADR 0082) and pushed manual codes (ADR 0092) both clear the
    physical lock slot via Z-Wave JS CC 99 before the DB row is deleted. Synced
    deletes fail-fast if the lock is unreachable. A manual code's delete refuses
    with :class:`SlotClearFailed` when a slot that may hold its PIN can't be
    cleared right now (slots it did clear are forgotten), and skips and records a
    lock latchpoint can't resolve to a Z-Wave node, since no clear can reach it.
    """
    code_id = code.id
    label = code.label
    user = code.user
    extra_metadata: dict[str, object] = {}
    manual = code.source != DoorCode.Source.SYNCED
    transient_failures: list[ClearFailure] = []
    permanent_failures: list[ClearFailure] = []

    if zwavejs is not None and manual:
        from locks.use_cases.lock_push import retry_failed_slot_clears

        # Clears an earlier update couldn't finish, including a dropped lock's.
        transient_failures.extend(retry_failed_slot_clears(door_code=code, zwavejs=zwavejs))

    cleared: list[dict[str, object]] = []
    has_pushed_slots = any(a.slot_index is not None for a in DoorCodeLockAssignment.objects.filter(door_code=code))
    if has_pushed_slots:
        assignments = list(DoorCodeLockAssignment.objects.filter(door_code=code))
        slots_to_clear = [
            {"lock_entity_id": a.lock_entity_id, "slot_index": int(a.slot_index)}
            for a in assignments
            if a.slot_index is not None
        ]

        # Clear slots on physical locks before deleting (ADR 0082 + 0092).
        if zwavejs is not None and slots_to_clear:
            from locks.use_cases.lock_config_sync import clear_lock_user_code_slot
            from locks.use_cases.lock_push import decrypt_pin_or_none, record_clear_failure

            already_failed = {(f.lock_entity_id, f.slot_index) for f in transient_failures}
            for slot_info in slots_to_clear:
                if (slot_info["lock_entity_id"], slot_info["slot_index"]) in already_failed:
                    continue  # its retry above just failed
                try:
                    clear_lock_user_code_slot(
                        lock_entity_id=slot_info["lock_entity_id"],
                        slot_index=slot_info["slot_index"],
                        zwavejs=zwavejs,
                        timeout_seconds=_REQUEST_CLEAR_TIMEOUT_SECONDS,
                    )
                    cleared.append(slot_info)
                except Exception as exc:
                    if code.source == DoorCode.Source.SYNCED:
                        # Synced codes still fail-fast (ADR 0082 contract).
                        raise
                    # Recorded (unless permanent) so the scheduler keeps retrying it
                    # if the delete is refused below.
                    failure = record_clear_failure(
                        door_code=code,
                        lock_entity_id=str(slot_info["lock_entity_id"]),
                        slot_index=int(slot_info["slot_index"]),
                        exc=exc,
                        expected_pin=decrypt_pin_or_none(code),
                    )
                    (permanent_failures if failure.permanent else transient_failures).append(failure)
            if cleared:
                extra_metadata["cleared_from_lock"] = True
                extra_metadata["cleared_slots"] = cleared
            if permanent_failures:
                # The lock can't be reached through latchpoint at all, so the code
                # still goes, with the slot recorded instead of silently forgotten.
                extra_metadata["failed_slot_clears"] = [f.as_metadata() for f in permanent_failures]

    # A still-pending push may have left the PIN in a slot recorded only as an
    # unconfirmed attempt; those events cascade away with the row, so check now.
    # That includes locks the code was dropped from since (issue #134).
    if zwavejs is not None:
        from locks.use_cases.lock_push import (
            clear_unconfirmed_slots_holding_pin,
            decrypt_pin_or_none,
            unconfirmed_attempt_lock_entity_ids,
        )

        pin = decrypt_pin_or_none(code)
        lock_entity_ids = list(
            dict.fromkeys(
                [
                    *DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", flat=True),
                    *unconfirmed_attempt_lock_entity_ids(door_code=code),
                ]
            )
        )
        if pin and lock_entity_ids:
            unconfirmed_cleared, unconfirmed_failures = clear_unconfirmed_slots_holding_pin(
                door_code=code,
                pin=pin,
                lock_entity_ids=lock_entity_ids,
                zwavejs=zwavejs,
            )
            if unconfirmed_cleared:
                extra_metadata["cleared_from_lock"] = True
                extra_metadata["cleared_unconfirmed_slots"] = unconfirmed_cleared
            # A manual code's delete is refused while a slot might still be cleared.
            # Whatever the delete goes ahead without checking (a lock latchpoint
            # can't reach any more, or any failure on a synced code) is kept in
            # the delete event, since its push_unconfirmed events go with the row.
            unchecked = [f for f in unconfirmed_failures if f.permanent or not manual]
            transient_failures.extend(f for f in unconfirmed_failures if manual and not f.permanent)
            if unchecked:
                extra_metadata["unconfirmed_slots_unchecked"] = [f.as_metadata() for f in unchecked]

    if transient_failures:
        _refuse_delete_after_failed_clears(
            code=code, actor_user=actor_user, cleared=cleared, failures=transient_failures
        )

    with transaction.atomic():
        # The code row first. code.delete() deletes the assignments before the
        # code row, and the scheduler's cap sweep takes the code row then its
        # assignments, so without this the two can deadlock (PR #195 review).
        DoorCode.objects.select_for_update().filter(id=code.id).first()
        DoorCodeEvent.objects.create(
            door_code=None,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_DELETED,
            metadata={"code_id": code_id, "label": label, "user_id": str(user.id), **extra_metadata},
        )

        code.delete()


def _refuse_delete_after_failed_clears(
    *,
    code: DoorCode,
    actor_user: User | None,
    cleared: list[dict[str, object]],
    failures: list[ClearFailure],
) -> None:
    """Keep a manual code whose PIN may still be on a lock, turn it off, and raise :class:`SlotClearFailed`.

    The code is turned off so the scheduler keeps retrying the failed clears
    without pushing it back onto any lock, including one a clear just freed.
    Slots that were cleared are forgotten so the row stays truthful.
    """
    from locks.use_cases.lock_push import clear_failures_message, forget_cleared_slot, refresh_push_state

    unique = {(f.lock_entity_id, f.slot_index): f for f in failures}
    message = clear_failures_message(list(unique.values()))
    for slot_info in cleared:
        forget_cleared_slot(
            door_code=code,
            lock_entity_id=str(slot_info["lock_entity_id"]),
            slot_index=int(slot_info["slot_index"]),
            outcome="cleared",
        )
    code.refresh_from_db(fields=["is_active"])
    if code.is_active:
        code.is_active = False
        code.save(update_fields=["is_active", "updated_at"])
        DoorCodeEvent.objects.create(
            door_code=code,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_UPDATED,
            metadata={"updated_fields": ["is_active"], "reason": "delete_refused"},
        )
    refresh_push_state(door_code=code)
    raise SlotClearFailed(f"{message}. The door code wasn't deleted and is now off, try again when the lock responds.")


def _request_push_best_effort(*, code: DoorCode, actor_user: User | None) -> None:
    """Queue the code's push (:func:`locks.use_cases.lock_push.request_push`) without raising into the API path.

    The save already happened, so a DB error queueing it doesn't fail the
    request, the same as :func:`_push_to_assigned_locks_best_effort`. The locks
    stay pending for the scheduler's 300s retry (PR #201 review).
    """
    try:
        from locks.use_cases.lock_push import request_push

        request_push(code, actor_user=actor_user)
    except Exception:
        logger.exception("Couldn't queue the push of door code id=%s; leaving it to the scheduler's retry", code.id)


def _push_to_assigned_locks_best_effort(
    *,
    code: DoorCode,
    zwavejs: ZwavejsGateway,
    actor_user: User | None,
) -> None:
    """Try to push the code to each assigned lock without raising into the API path.

    Failures persist on the row (``push_state``, ``last_push_error``) and are
    picked up by the scheduler retry. The HTTP caller still gets a 201/200 with
    the saved row. The inline fallback for a process that doesn't run the push
    task (issue #124), so each lock gets :data:`PUSH_LOCK_BUDGET_SECONDS`.
    """
    try:
        from locks.use_cases.lock_push import PUSH_LOCK_BUDGET_SECONDS, push_door_code_to_assigned_locks

        push_door_code_to_assigned_locks(
            door_code=code,
            zwavejs=zwavejs,
            actor_user=actor_user,
            only_unassigned=True,
            lock_budget_seconds=PUSH_LOCK_BUDGET_SECONDS,
        )
    except Exception:
        # Unexpected error from the push pipeline. Per-lock failures are recorded
        # on the row by lock_push itself; this branch only fires for *unhandled*
        # exception types (import errors during partial deploy, programming bugs,
        # etc). Log + stamp a generic message so the UI doesn't show "pending"
        # with no diagnostic.
        logger.exception("Unhandled error pushing door code id=%s; row left at last persisted state", code.id)
        try:
            DoorCode.objects.filter(id=code.id).update(
                last_push_error="Internal error during push (see backend logs)",
                last_push_attempt_at=django_timezone.now(),
            )
        except Exception:  # pragma: no cover - belt-and-suspenders
            logger.exception("Failed to stamp last_push_error for door code id=%s", code.id)


def retry_push_door_code(
    *,
    code: DoorCode,
    actor_user: User | None,
    zwavejs: ZwavejsGateway,
) -> DoorCode:
    """Admin-triggered manual retry.

    Retries any slot clears that failed first, then re-arms every ``failed``
    lock (and every ``pending`` one at the attempt cap) and resets the code's
    clear-retry count (issue #126), then pushes every lock that needs it: no
    slot (which includes a kept lock whose stale slot just got cleared), or a
    slot whose schedule is pending, which only gets the schedule. An
    inactive code is only retried when it has clears outstanding, which
    includes a slot it still holds or an unconfirmed attempt slot left to check
    (issue #158), and is never pushed.

    The same goes for an active code before its ``start_at`` (issue #145): it's
    only retried when it has clears outstanding (a clear failure on record, or a
    slot it may still hold), which are retried and withdrawn without pushing it,
    and it gets a 409 when there's nothing to clear. An active code past its
    ``end_at`` that the scheduler hasn't turned off yet is retired right away
    (:func:`retire_door_code`) instead of being retried (PR #183 review).

    The clear retries run in the request but only for
    :data:`_RETRY_CLEAR_BUDGET_SECONDS` together; the ones that don't fit stay
    on record for the scheduler. The push of an active code is then queued for
    the scheduler (:func:`locks.use_cases.lock_push.request_push`), or made
    inline with each lock's budget where that doesn't run in this process
    (issue #124).
    """
    assert_admin(user=actor_user) if actor_user is not None else None

    from locks.tasks import _get_push_max_attempts
    from locks.use_cases.lock_push import (
        PUSH_LOCK_BUDGET_SECONDS,
        inactive_slots_to_clear,
        push_or_settle_after_clear_retry,
        push_task_running,
        rearm_failed_locks,
        refresh_push_state,
        retry_failed_slot_clears,
        slots_to_withdraw,
        unresolved_clear_failures,
    )

    def fresh() -> DoorCode:
        return DoorCode.objects.select_related("user").prefetch_related("lock_assignments").get(id=code.id)

    if code.is_active and is_expired(code):
        # Resetting a failed push to pending here would zero the attempt cap and
        # could mark it pushed, so take it off its locks now like the scheduler would.
        if retire_door_code(code=code, reason="expired", zwavejs=zwavejs) is not None:
            return fresh()
        # Left alone: turned off, given a later end_at or deleted meanwhile.
        try:
            code.refresh_from_db()
        except DoorCode.DoesNotExist as exc:
            raise NotFound("Not found.") from exc

    if (
        not code.is_active
        and not unresolved_clear_failures(door_code=code)
        and not inactive_slots_to_clear(door_code=code)
    ):
        raise DoorCodeInactive("Door code is inactive. Turn it on before pushing it to its locks.")
    not_started = code.is_active and not is_started(code)
    if not_started and not unresolved_clear_failures(door_code=code) and not slots_to_withdraw(door_code=code):
        raise DoorCodeNotStarted("Door code hasn't started yet. It goes on its locks at its start time.")

    retry_failed_slot_clears(door_code=code, zwavejs=zwavejs, budget_seconds=_RETRY_CLEAR_BUDGET_SECONDS)

    # A failed lock or a capped clear was given up on by the scheduler; an
    # explicit retry is the operator saying "yes, try again". So every failed
    # lock, and every pending one already at the cap, goes back to pending with
    # no attempts, and the code's clear-retry count goes back to 0 (issue #126).
    # The rollup then shows whatever is still outstanding.
    with transaction.atomic():
        DoorCode.objects.select_for_update().filter(id=code.id).first()
        DoorCode.objects.filter(id=code.id).update(push_attempt_count=0)
        rearm_failed_locks(door_code=code, max_attempts=_get_push_max_attempts())

    if not_started:
        # Never pushed before its start. Take off anything it may still hold that
        # has no clear failure on record (the retries above handled those), and
        # keep a clear that's still failing on show so the scheduler retries it.
        try:
            withdraw_door_code(code=code, zwavejs=zwavejs)
        finally:
            refresh_push_state(door_code=code)
        return fresh()

    if code.is_active and push_task_running():
        # Every failed lock was re-armed above, so the queued push gets them too.
        _request_push_best_effort(code=code, actor_user=actor_user)
        refresh_push_state(door_code=code)
        return fresh()

    push_or_settle_after_clear_retry(
        door_code=code,
        zwavejs=zwavejs,
        actor_user=actor_user,
        include_failed=True,
        lock_budget_seconds=PUSH_LOCK_BUDGET_SECONDS,
    )
    return fresh()
