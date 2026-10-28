from __future__ import annotations

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

logger = logging.getLogger(__name__)

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
        # Refresh so the freshly-created assignments are visible to push.
        code = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        _push_to_assigned_locks_best_effort(code=code, zwavejs=zwavejs, actor_user=actor_user)

    return code


# Fields whose change requires re-pushing the code onto the physical lock.
# ``start_at`` / ``end_at`` are deliberately excluded — they are validity-window
# fields enforced in software, never programmed onto the lock.
_PUSH_TRIGGER_FIELDS = frozenset({"code", "is_active", "days_of_week", "window_start", "window_end"})


def _changed_push_trigger_fields(*, code: DoorCode, changes: dict, old_pin: str | None) -> set[str]:
    """Return the push trigger fields in ``changes`` whose value differs from ``code``'s.

    The edit form sends every field on every save, so a key being present doesn't
    mean it changed (issue #139). Call before ``changes`` is applied.
    """
    from locks.use_cases.lock_push import has_unconfirmed_attempt_slots

    changed: set[str] = set()
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


def update_door_code(
    *,
    code: DoorCode,
    changes: dict,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
) -> DoorCode:
    """Update a door code and its lock assignments, emitting a `DoorCodeEvent` when changed.

    When ``zwavejs`` is provided, dropped locks' slots are CC 99 ``clear``-ed. A
    change to a push-relevant field's value clears and re-pushes every lock; a
    lock-list-only change keeps the surviving locks' slots and pushes only locks
    without one. An inactive code is never pushed. A slot whose clear fails
    transiently stays tracked (a dropped lock keeps its assignment), is recorded
    per lock for the scheduler and Retry to clear later, and keeps the code from
    showing ``pushed``. A lock latchpoint can't resolve to a Z-Wave node any more
    is dropped or forgotten anyway, since no clear can reach it.
    """
    updated_fields = []

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
            mark_pushed_if_settled,
            record_clear_failure,
            resolve_clear_failure,
            settle_clear_failure_state,
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
        metadata: dict[str, object] = {"updated_fields": updated_fields}
        if added_lock_entity_ids:
            metadata["added_lock_entity_ids"] = added_lock_entity_ids
        if removed_lock_entity_ids:
            metadata["removed_lock_entity_ids"] = removed_lock_entity_ids
        updated_event = DoorCodeEvent.objects.create(
            door_code=code,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_UPDATED,
            metadata=metadata,
        )

    if zwavejs is not None:
        # A pending code's PIN may sit in a slot recorded only as an unconfirmed
        # attempt. Clear it where the code no longer belongs there with that PIN:
        # dropped locks always, surviving locks when the PIN changes or the code is
        # deactivated. (A schedule-only change re-pushes and adopts it instead.)
        deactivating = "is_active" in push_trigger_changes and not code.is_active
        unconfirmed_lock_ids = list(dropped_lock_entity_ids)
        if "code" in push_trigger_changes or deactivating:
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
                code.push_state = DoorCode.PushState.PENDING
                code.last_push_error = ""
                code.push_attempt_count = 0
                code.save(update_fields=["push_state", "last_push_error", "push_attempt_count", "updated_at"])

            if not code.is_active:
                # An inactive code is never pushed (issue #138).
                if push_relevant_change:
                    # Deactivation (or a change to an inactive code): the lock holds
                    # no programmed slots for this code anymore, so stop here.
                    code.push_state = DoorCode.PushState.PUSHED
                    code.last_push_attempt_at = django_timezone.now()
                    code.save(update_fields=["push_state", "last_push_attempt_at", "updated_at"])
            else:
                code = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
                _push_to_assigned_locks_best_effort(code=code, zwavejs=zwavejs, actor_user=actor_user)
                if dropped_lock_entity_ids and not push_relevant_change:
                    # Locks that stay aren't re-pushed, so nothing recomputes
                    # push_state and a failure left by a dropped lock would stick.
                    mark_pushed_if_settled(door_code=code)

        # Last, so neither the push's own state nor the pushed stamps above can
        # show a code pushed while a lock may still hold its PIN.
        settle_clear_failure_state(door_code=code)
        if failed_slot_clears and updated_event is not None:
            updated_event.metadata["failed_slot_clears"] = [f.as_metadata() for f in failed_slot_clears]
            updated_event.save(update_fields=["metadata"])

    return code


def delete_door_code(
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
    if zwavejs is not None:
        from locks.use_cases.lock_push import clear_unconfirmed_slots_holding_pin, decrypt_pin_or_none

        pin = decrypt_pin_or_none(code)
        lock_entity_ids = list(
            DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", flat=True)
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
            if manual:
                transient_failures.extend(unconfirmed_failures)

    if transient_failures:
        _refuse_delete_after_failed_clears(
            code=code, actor_user=actor_user, cleared=cleared, failures=transient_failures
        )

    with transaction.atomic():
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
    from locks.use_cases.lock_push import clear_failures_message, forget_cleared_slot, settle_clear_failure_state

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
    settle_clear_failure_state(door_code=code)
    raise SlotClearFailed(f"{message}. The door code wasn't deleted and is now off, try again when the lock responds.")


def _push_to_assigned_locks_best_effort(
    *,
    code: DoorCode,
    zwavejs: ZwavejsGateway,
    actor_user: User | None,
) -> None:
    """Try to push the code to each assigned lock without raising into the API path.

    Failures persist on the row (``push_state``, ``last_push_error``) and are
    picked up by the scheduler retry. The HTTP caller still gets a 201/200 with
    the saved row.
    """
    try:
        from locks.use_cases.lock_push import push_door_code_to_assigned_locks

        push_door_code_to_assigned_locks(
            door_code=code,
            zwavejs=zwavejs,
            actor_user=actor_user,
            only_unassigned=True,
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

    Retries any slot clears that failed first, then pushes every lock without a
    slot (which includes a kept lock whose stale slot just got cleared). An
    inactive code is only retried when it has clears outstanding, and is never
    pushed.
    """
    assert_admin(user=actor_user) if actor_user is not None else None

    from locks.use_cases.lock_push import (
        push_or_settle_after_clear_retry,
        retry_failed_slot_clears,
        unresolved_clear_failures,
    )

    if not code.is_active and not unresolved_clear_failures(door_code=code):
        raise DoorCodeInactive("Door code is inactive. Turn it on before pushing it to its locks.")

    retry_failed_slot_clears(door_code=code, zwavejs=zwavejs)

    # Failed codes were intentionally retired by the scheduler; an explicit retry
    # is the operator saying "yes, try again," so re-arm pending state and zero
    # the cap counter. A clear that's still failing puts its error back afterwards.
    code.refresh_from_db(fields=["push_state"])
    if code.push_state == DoorCode.PushState.FAILED:
        code.push_state = DoorCode.PushState.PENDING
        code.last_push_error = ""
        code.push_attempt_count = 0
        code.save(update_fields=["push_state", "last_push_error", "push_attempt_count", "updated_at"])

    push_or_settle_after_clear_retry(door_code=code, zwavejs=zwavejs, actor_user=actor_user)
    return DoorCode.objects.select_related("user").prefetch_related("lock_assignments").get(id=code.id)
