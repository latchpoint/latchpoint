from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.db.models import Exists, OuterRef, Q
from django.db.models import QuerySet

from accounts.models import User
from accounts.policies import is_admin
from config.domain_exceptions import ForbiddenError, NotFoundError, ValidationError
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment


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
    has_active_assignment = Exists(
        DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk"), sync_dismissed=False)
    )
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
    code = (
        DoorCode.objects.select_related("user")
        .prefetch_related("lock_assignments")
        .filter(id=code_id)
        .first()
    )
    if not code:
        raise NotFound("Not found.")
    return code


def get_door_code_for_admin_update(*, actor_user: User, code_id: int) -> DoorCode:
    """Fetch a door code for admin update, enforcing admin permissions and raising `NotFound`."""
    assert_admin(user=actor_user)
    code = (
        DoorCode.objects.select_related("user")
        .prefetch_related("lock_assignments")
        .filter(id=code_id)
        .first()
    )
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
) -> DoorCode:
    """Create a door code, assign it to locks (optional), and emit a `DoorCodeEvent`."""
    raw_code = (raw_code or "").strip()
    code = DoorCode.objects.create(
        user=user,
        code_hash=make_password(raw_code),
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

    return code


def update_door_code(
    *,
    code: DoorCode,
    changes: dict,
    actor_user: User | None = None,
) -> DoorCode:
    """Update a door code and its lock assignments, emitting a `DoorCodeEvent` when changed."""
    updated_fields = []

    if "code" in changes and changes.get("code"):
        raw_code = str(changes.get("code") or "").strip()
        code.code_hash = make_password(raw_code)
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

    if "lock_entity_ids" in changes:
        lock_entity_ids = changes.get("lock_entity_ids") or []
        code.lock_assignments.all().delete()

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
        updated_fields.append("lock_entity_ids")

    if updated_fields:
        DoorCodeEvent.objects.create(
            door_code=code,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_UPDATED,
            metadata={"updated_fields": updated_fields},
        )

    return code


def list_dismissed_assignments(*, lock_entity_id: str) -> list[DoorCodeLockAssignment]:
    """Return all sync-dismissed assignments for a given lock, with their door codes."""
    return list(
        DoorCodeLockAssignment.objects.select_related("door_code", "door_code__user")
        .filter(lock_entity_id=lock_entity_id, sync_dismissed=True)
        .order_by("slot_index")
    )


def undismiss_assignment(*, assignment_id: int) -> DoorCodeLockAssignment:
    """Clear sync_dismissed on an assignment, re-enabling sync for that slot."""
    assignment = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(id=assignment_id, sync_dismissed=True)
        .first()
    )
    if not assignment:
        raise NotFound("Dismissed assignment not found.")

    assignment.sync_dismissed = False
    assignment.save(update_fields=["sync_dismissed", "updated_at"])

    code = assignment.door_code
    if code and not code.is_active:
        code.is_active = True
        code.save(update_fields=["is_active", "updated_at"])

    return assignment


def delete_door_code(
    *,
    code: DoorCode,
    actor_user: User | None = None,
) -> None:
    """Delete a door code and emit a `DoorCodeEvent` capturing who deleted it."""
    code_id = code.id
    label = code.label
    user = code.user

    if code.source == DoorCode.Source.SYNCED:
        from django.utils import timezone as django_timezone

        now = django_timezone.now()
        assignments = list(DoorCodeLockAssignment.objects.filter(door_code=code))
        dismissed_slots = [
            {"lock_entity_id": a.lock_entity_id, "slot_index": int(a.slot_index)}
            for a in assignments
            if a.slot_index is not None
        ]
        DoorCodeLockAssignment.objects.filter(door_code=code).update(sync_dismissed=True, updated_at=now)
        if code.is_active:
            code.is_active = False
            code.save(update_fields=["is_active", "updated_at"])

        DoorCodeEvent.objects.create(
            door_code=None,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_DELETED,
            metadata={
                "code_id": code_id,
                "label": label,
                "user_id": str(user.id),
                "dismissed": True,
                "dismissed_slots": dismissed_slots,
            },
        )
        return

    DoorCodeEvent.objects.create(
        door_code=None,
        user=actor_user,
        event_type=DoorCodeEvent.EventType.CODE_DELETED,
        metadata={"code_id": code_id, "label": label, "user_id": str(user.id)},
    )

    code.delete()
