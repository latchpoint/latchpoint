from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone as django_timezone

from accounts.models import User
from accounts.policies import is_admin
from alarm.crypto import SettingsEncryption
from config.domain_exceptions import ForbiddenError, NotFoundError, ValidationError
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment

if TYPE_CHECKING:
    from alarm.gateways.zwavejs import ZwavejsGateway


class Forbidden(ForbiddenError):
    pass


class NotFound(NotFoundError):
    pass


class ReauthRequired(ValidationError):
    pass


class ReauthFailed(ForbiddenError):
    pass


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


def update_door_code(
    *,
    code: DoorCode,
    changes: dict,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
) -> DoorCode:
    """Update a door code and its lock assignments, emitting a `DoorCodeEvent` when changed.

    When ``zwavejs`` is provided and either (a) a push-relevant field changed or
    (b) the assigned lock set changed, re-push to surviving + new locks and CC 99
    ``clear`` any dropped locks' slots.
    """
    updated_fields = []

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

    # Snapshot old assignments BEFORE swap so we can clear dropped locks' slots.
    dropped_slot_clears: list[dict[str, object]] = []
    if "lock_entity_ids" in changes:
        new_entity_ids = set(changes.get("lock_entity_ids") or [])
        old_assignments = list(DoorCodeLockAssignment.objects.filter(door_code=code))
        for assignment in old_assignments:
            if assignment.lock_entity_id in new_entity_ids:
                continue
            if assignment.slot_index is None:
                continue
            dropped_slot_clears.append(
                {"lock_entity_id": assignment.lock_entity_id, "slot_index": int(assignment.slot_index)}
            )

        code.lock_assignments.all().delete()

        if new_entity_ids:
            DoorCodeLockAssignment.objects.bulk_create(
                [
                    DoorCodeLockAssignment(
                        door_code=code,
                        lock_entity_id=entity_id,
                    )
                    for entity_id in new_entity_ids
                ],
                ignore_conflicts=True,
            )
        updated_fields.append("lock_entity_ids")

    if updated_fields:
        DoorCodeEvent.objects.create(
            door_code=code,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_UPDATED,
            metadata={"updated_fields": updated_fields},
        )

    if zwavejs is not None:
        from locks.use_cases.lock_config_sync import clear_lock_user_code_slot

        for clear_info in dropped_slot_clears:
            # Best-effort: a dropped lock that's currently offline shouldn't fail
            # the PATCH. The slot will hang until pull-sync reconciles, which is
            # acceptable.
            with contextlib.suppress(Exception):
                clear_lock_user_code_slot(
                    lock_entity_id=str(clear_info["lock_entity_id"]),
                    slot_index=int(clear_info["slot_index"]),
                    zwavejs=zwavejs,
                )

        push_relevant_change = bool(_PUSH_TRIGGER_FIELDS & set(changes.keys()))
        if push_relevant_change or "lock_entity_ids" in changes:
            now_inactive = "is_active" in changes and not bool(changes.get("is_active"))

            stale_slot_clears: list[dict[str, object]] = []
            if push_relevant_change:
                # PIN, schedule, or is_active changed. The lock still holds the OLD
                # PIN at the OLD slot; pushing fresh would pick a *different* slot
                # and strand the old PIN — breaking the ADR's "Created in the UI =
                # works on the door" guarantee. Snapshot the existing programmed
                # slots so we can clear them before the re-push runs.
                existing_pushed = DoorCodeLockAssignment.objects.filter(door_code=code, slot_index__isnull=False)
                for assignment in existing_pushed:
                    stale_slot_clears.append(
                        {
                            "lock_entity_id": assignment.lock_entity_id,
                            "slot_index": int(assignment.slot_index),
                        }
                    )
                # Force a re-push by zeroing slots + counter; surviving assignments
                # are treated as unassigned by the use case.
                DoorCodeLockAssignment.objects.filter(door_code=code).update(slot_index=None)
                code.push_state = DoorCode.PushState.PENDING
                code.last_push_error = ""
                code.push_attempt_count = 0
                code.save(update_fields=["push_state", "last_push_error", "push_attempt_count", "updated_at"])

            for clear_info in stale_slot_clears:
                with contextlib.suppress(Exception):
                    clear_lock_user_code_slot(
                        lock_entity_id=str(clear_info["lock_entity_id"]),
                        slot_index=int(clear_info["slot_index"]),
                        zwavejs=zwavejs,
                    )

            if now_inactive:
                # Deactivation: stop here. The lock holds no programmed slots for
                # this code anymore, so a re-push would just program it back on.
                code.push_state = DoorCode.PushState.PUSHED
                code.last_push_attempt_at = django_timezone.now()
                code.save(update_fields=["push_state", "last_push_attempt_at", "updated_at"])
            else:
                code = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
                _push_to_assigned_locks_best_effort(code=code, zwavejs=zwavejs, actor_user=actor_user)

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
    deletes fail-fast if the lock is unreachable; manual-code deletes are
    best-effort because the row can outlive a removed lock.
    """
    code_id = code.id
    label = code.label
    user = code.user
    extra_metadata: dict[str, object] = {}

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

            cleared: list[dict[str, object]] = []
            for slot_info in slots_to_clear:
                try:
                    clear_lock_user_code_slot(
                        lock_entity_id=slot_info["lock_entity_id"],
                        slot_index=slot_info["slot_index"],
                        zwavejs=zwavejs,
                    )
                    cleared.append(slot_info)
                except Exception:
                    if code.source == DoorCode.Source.SYNCED:
                        # Synced codes still fail-fast (ADR 0082 contract).
                        raise
            if cleared:
                extra_metadata["cleared_from_lock"] = True
                extra_metadata["cleared_slots"] = cleared

    with transaction.atomic():
        DoorCodeEvent.objects.create(
            door_code=None,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_DELETED,
            metadata={"code_id": code_id, "label": label, "user_id": str(user.id), **extra_metadata},
        )

        code.delete()


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
        # _push_to_assigned_locks already records failures on the row; this guards
        # against e.g. import errors during partial deploys.
        pass


def retry_push_door_code(
    *,
    code: DoorCode,
    actor_user: User | None,
    zwavejs: ZwavejsGateway,
) -> DoorCode:
    """Admin-triggered manual retry — runs the push pipeline for every unassigned lock."""
    assert_admin(user=actor_user) if actor_user is not None else None

    # Failed codes were intentionally retired by the scheduler; an explicit retry
    # is the operator saying "yes, try again," so re-arm pending state and zero
    # the cap counter.
    if code.push_state == DoorCode.PushState.FAILED:
        code.push_state = DoorCode.PushState.PENDING
        code.last_push_error = ""
        code.push_attempt_count = 0
        code.save(update_fields=["push_state", "last_push_error", "push_attempt_count", "updated_at"])

    from locks.use_cases.lock_push import push_door_code_to_assigned_locks

    push_door_code_to_assigned_locks(
        door_code=code,
        zwavejs=zwavejs,
        actor_user=actor_user,
        only_unassigned=True,
    )
    return DoorCode.objects.select_related("user").prefetch_related("lock_assignments").get(id=code.id)
