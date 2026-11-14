from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import Error as DbError
from django.db import transaction
from django.db.models import Exists, F, OuterRef, ProtectedError, Q, QuerySet
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
# A guess, not timed on the real locks yet (issue #203).
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


class DuplicatePinOnLock(ConflictError):
    """Turning a code on whose PIN another code already has on one of its locks (issue #188).

    The push would put the PIN in a second slot, so it's refused before
    anything changes.
    """


class DoorCodeWouldHaveNoLocks(ValidationError):
    """Lock removals on an update that would leave the code on no lock (issue #159)."""


class DoorCodePinUnknown(ValidationError):
    """Adding a lock to a code whose PIN latchpoint doesn't have, so there's nothing to push.

    A synced code imported from a lock that masks its codes has no stored PIN,
    and a stored PIN that can't be decrypted counts the same.
    """


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
            # Refresh so the freshly-created assignments are visible to push. One
            # deleted meanwhile has nothing to push (issue #189).
            fresh = DoorCode.objects.prefetch_related("lock_assignments").filter(id=code.id).first()
            if fresh is not None:
                code = fresh
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
    at most :data:`SYNC_LOCK_WAIT_SECONDS`. While it waits, the queued push task
    leaves these locks alone (``announce_wait``, issue #203).
    Re-reads ``code`` from the DB once held, raising :class:`NotFound` if it's gone.
    """
    from locks.use_cases.lock_config_sync import hold_lock_sync, sync_lock_deadline
    from locks.use_cases.lock_push import affected_lock_entity_ids

    deadline = sync_lock_deadline()
    extra = set(extra_lock_entity_ids or ())
    wanted = extra | affected_lock_entity_ids(door_code=code)
    while True:
        with hold_lock_sync(wanted, deadline=deadline, announce_wait=True):
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
    extra_lock_entity_ids = [*(changes.get("lock_entity_ids") or ()), *(changes.get("add_lock_entity_ids") or ())]
    with _hold_door_code_locks(code=code, extra_lock_entity_ids=extra_lock_entity_ids):
        code, push_inline = _update_door_code_locked(
            code=code, changes=changes, actor_user=actor_user, zwavejs=zwavejs, convert_without_import_lock=True
        )
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

    Synced copies of its PIN on its locks (issue #185) are found first, while
    the code still tracks its slots (:func:`_synced_copies_of_pin`). One that's
    a stranded copy of this code (:func:`_is_stranded_copy`) goes through the
    same locked deactivate once this code is off, still under these locks, so
    its slot is cleared (and a clear that fails is retried) and its
    ``code_updated`` event says which code it was a copy of. If that raises, a
    ``duplicate_retire_pending`` event on this code has the validity task try
    it again each tick, up to ``door_codes.push_max_attempts``
    (:func:`retry_pending_copy_retires`). Any other copy is
    left alone and only flagged, with a ``duplicate_pin_survives_retire`` event
    on this code and a warning, since it may be someone's own keypad code that
    happens to share the PIN (PR #211 review).
    """
    try:
        with _hold_door_code_locks(code=code):
            check_at = now if now is not None else django_timezone.now()
            if not code.is_active or not is_expired(code, now=check_at):
                return None
            copies = [
                (
                    copy_id,
                    lock_entity_id,
                    slot_index,
                    _is_stranded_copy(
                        original=code, copy_id=copy_id, lock_entity_id=lock_entity_id, slot_index=slot_index
                    ),
                )
                for copy_id, lock_entity_id, slot_index in _synced_copies_of_pin(code=code)
            ]
            # A deactivate, so there's never a push to make afterwards.
            code, _push_inline = _update_door_code_locked(
                code=code,
                changes={"is_active": False},
                actor_user=None,
                zwavejs=zwavejs,
                event_metadata={"reason": reason},
            )
            for copy_id, lock_entity_id, slot_index, stranded in copies:
                outcome = _retire_synced_copy(copy_id=copy_id, original=code, zwavejs=zwavejs) if stranded else None
                if not stranded or outcome == _COPY_LEFT_ALONE:
                    _flag_surviving_duplicate(
                        original=code, copy_id=copy_id, lock_entity_id=lock_entity_id, slot_index=slot_index
                    )
                elif not outcome:
                    _record_copy_event(
                        original=code,
                        action=_COPY_RETIRE_PENDING,
                        copy_id=copy_id,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                    )
            return code
    except NotFound:
        return None


# DoorCodeEvent metadata ``action`` values on the retired code for its synced copies (issue #185, PR #211 review).
_COPY_SURVIVES_RETIRE = "duplicate_pin_survives_retire"
_COPY_RETIRE_PENDING = "duplicate_retire_pending"
_COPY_RETIRE_DONE = "duplicate_retire_done"
_COPY_RETIRE_FAILED = "duplicate_retire_failed"


def _synced_copies_of_pin(*, code: DoorCode) -> list[tuple[int, str, int]]:
    """``(copy id, lock, slot)`` of synced codes that hold ``code``'s PIN in a slot on one of its locks.

    The duplicates lock sync flags ``duplicate_pin`` (issue #140). Only active
    synced codes, since a manual code's dates and state are someone's own
    choice, and only ones without an ``end_at``, since a copy with its own
    dates is retired by them. The PIN has to match exactly, so a masked slot
    never counts.
    """
    from locks.use_cases.lock_push import decrypt_pin_or_none

    pin = decrypt_pin_or_none(code)
    if not pin:
        return []
    lock_entity_ids = DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", flat=True)
    candidates = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(
            lock_entity_id__in=list(lock_entity_ids),
            slot_index__isnull=False,
            door_code__source=DoorCode.Source.SYNCED,
            door_code__is_active=True,
            door_code__end_at__isnull=True,
        )
        .exclude(door_code=code)
        .order_by("door_code_id", "lock_entity_id")
    )
    return [
        (a.door_code_id, a.lock_entity_id, int(a.slot_index))
        for a in candidates
        if decrypt_pin_or_none(a.door_code) == pin
    ]


def _is_stranded_copy(*, original: DoorCode, copy_id: int, lock_entity_id: str, slot_index: int) -> bool:
    """Whether the synced copy in this slot is left over from ``original``'s own push there, ie safe to retire with it.

    Both of these, with the PIN match :func:`_synced_copies_of_pin` already did

    - a push of ``original`` landed in this exact slot on this lock (a
      ``code_synced`` event with ``action=pushed`` and this ``slot_index``),
      which is where a copy #133 stranded sits
    - the copy's row was created after the first of those pushes, ie lock sync
      imported what that push left there

    Anything else isn't one, a lock sync's ``duplicate_pin_door_code_ids``
    included, since sync records any two codes with the same PIN on a lock
    against each other. That keeps a family member's keypad code whose PIN a
    guest code was given later (PR #211 review), whether the guest's push was
    dropped or landed in another slot, and a keypad code typed in after the
    guest's push into a slot the guest never used. Event retention keeps an
    active dated code's first push per lock and slot
    (:func:`first_push_event_ids_of_dated_codes`, issue #212). With no push
    event left for the slot anyway (pruned before that, or while the code was
    off or had no ``end_at``) the copy is flagged instead of retired.

    A synced code latchpoint has pushed to any of its locks isn't one either,
    whichever slot this is. Someone added a lock to it (ADR 0082), so it's a
    code they use on purpose, and turning it off would take it off the locks
    they added too. It's only flagged. Its row's ``created_at`` is when it was
    imported from its first lock, so it says nothing about a slot latchpoint
    pushed it into. That's a push attempt or a queued push on any of its
    assignments, slot or not
    (:func:`~locks.use_cases.lock_push.has_lock_pushed_by_latchpoint`), which
    lock sync never stamps and event retention never prunes. It's broad on
    purpose, since leaving a code alone only means flagging it.
    """
    from locks.use_cases.lock_push import has_lock_pushed_by_latchpoint

    if has_lock_pushed_by_latchpoint(door_code_id=copy_id):
        return False
    first_push_at = (
        DoorCodeEvent.objects.filter(
            door_code=original,
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata__action="pushed",
            metadata__slot_index=int(slot_index),
        )
        .order_by("created_at", "id")
        .values_list("created_at", flat=True)
        .first()
    )
    if first_push_at is None:
        return False
    copy_created_at = DoorCode.objects.filter(id=copy_id).values_list("created_at", flat=True).first()
    return copy_created_at is not None and copy_created_at > first_push_at


def first_push_event_ids_of_dated_codes(*, older_than) -> set[int]:
    """Each active code with an ``end_at``'s first ``code_synced`` push per lock and slot, which event retention keeps.

    That push is what :func:`_is_stranded_copy` dates a copy against when the
    code is retired, so pruning it left a stranded copy flagged only and its
    PIN opening the door past the code's ``end_at`` (issue #212). Only active
    codes with an ``end_at`` are retired, and only on the locks they're still
    on, so a lock the code was taken off (or is being taken off) doesn't keep
    its push. Only pushes older than ``older_than`` are read, since retention
    leaves the newer ones anyway, and the oldest of those is the first one when
    there is one. It's a row or two per lock for each of those codes.
    """
    from locks.use_cases.lock_push import being_removed_q

    still_on_lock = DoorCodeLockAssignment.objects.filter(
        door_code=OuterRef("door_code"), lock_entity_id=OuterRef("lock_entity_id")
    ).exclude(being_removed_q())
    first: dict[tuple[int, str, int], int] = {}
    pushes = (
        DoorCodeEvent.objects.filter(
            created_at__lt=older_than,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata__action="pushed",
            door_code__is_active=True,
            door_code__end_at__isnull=False,
        )
        .filter(Exists(still_on_lock))
        .order_by("created_at", "id")
        .values_list("id", "door_code_id", "lock_entity_id", "metadata")
    )
    for event_id, door_code_id, lock_entity_id, metadata in pushes:
        slot_index = metadata.get("slot_index") if isinstance(metadata, dict) else None
        if isinstance(slot_index, int):
            first.setdefault((door_code_id, lock_entity_id, slot_index), event_id)
    return set(first.values())


def _record_copy_event(
    *, original: DoorCode, action: str, copy_id: int, lock_entity_id: str, slot_index: int, **extra: object
) -> None:
    """A ``code_failed`` event on ``original`` about a synced copy of its PIN. Never the PIN."""
    DoorCodeEvent.objects.create(
        door_code=original,
        user=None,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={"action": action, "slot_index": int(slot_index), "duplicate_door_code_id": int(copy_id), **extra},
    )


def _flag_surviving_duplicate(*, original: DoorCode, copy_id: int, lock_entity_id: str, slot_index: int) -> None:
    """Record that a synced code with ``original``'s PIN keeps working on this lock after its retire (issue #185)."""
    logger.warning(
        "Retired door code id=%d, but synced door code id=%d in slot %d on %s holds the same PIN and wasn't touched",
        original.id,
        copy_id,
        slot_index,
        lock_entity_id,
    )
    _record_copy_event(
        original=original,
        action=_COPY_SURVIVES_RETIRE,
        copy_id=copy_id,
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
    )


_COPY_RETIRED = "retired"
_COPY_LEFT_ALONE = "left_alone"
# Nothing left to retire (issue #212): the copy was deleted, or it's off, has
# an ``end_at``, holds another PIN or isn't synced any more.
_COPY_GONE = "gone"
_COPY_CHANGED = "changed"


def _retire_synced_copy(*, copy_id: int, original: DoorCode, zwavejs: ZwavejsGateway) -> str | None:
    """Turn off a stranded synced copy of ``original``'s PIN and clear its slot (issue #185).

    The copy is read again under its own locks (when called from
    :func:`retire_door_code` the original's already cover its slot, so this only
    waits for a lock it has a clear or attempt on elsewhere) and left alone if
    it's gone (:data:`_COPY_GONE`), or off, given an ``end_at``, holds a
    different PIN or isn't synced by then (:data:`_COPY_CHANGED`), since
    there's nothing left to do (issue #212). It's :data:`_COPY_RETIRED` once
    it's turned off here. It's
    :data:`_COPY_LEFT_ALONE` when someone has added a lock to it by then
    (:func:`_is_stranded_copy`), checked under those locks so an add that
    landed after the caller looked is still seen, and the caller flags it
    instead. ``None`` (falsy) only when the retire raised (logged), so the
    caller can have it tried again.
    """
    copy = DoorCode.objects.filter(id=copy_id).first()
    if copy is None:
        return _COPY_GONE
    try:
        with _hold_door_code_locks(code=copy):
            not_a_candidate = _copy_not_a_candidate(copy=copy, original=original)
            if not_a_candidate:
                return not_a_candidate
            _update_door_code_locked(
                code=copy,
                changes={"is_active": False},
                actor_user=None,
                zwavejs=zwavejs,
                event_metadata={"reason": "duplicate_of_retired_code", "duplicate_of_door_code_id": original.id},
            )
            return _COPY_RETIRED
    except NotFound:
        return _COPY_GONE
    except Exception:
        logger.warning(
            "Couldn't retire synced door code id=%d, a copy of retired door code id=%d's PIN; trying again next tick",
            copy_id,
            original.id,
            exc_info=True,
        )
        return None


def _copy_not_a_candidate(*, copy: DoorCode | None, original: DoorCode) -> str | None:
    """Why ``copy`` isn't a stranded copy to retire any more, or ``None`` when it still is.

    :data:`_COPY_GONE`, :data:`_COPY_LEFT_ALONE` (someone added a lock to it)
    or :data:`_COPY_CHANGED`, the same checks :func:`_retire_synced_copy`
    makes under the copy's locks.
    """
    from locks.use_cases.lock_push import decrypt_pin_or_none, has_lock_pushed_by_latchpoint

    if copy is None:
        return _COPY_GONE
    if has_lock_pushed_by_latchpoint(door_code_id=copy.id):
        return _COPY_LEFT_ALONE
    if (
        copy.source != DoorCode.Source.SYNCED
        or not copy.is_active
        or copy.end_at is not None
        or decrypt_pin_or_none(copy) != decrypt_pin_or_none(original)
    ):
        return _COPY_CHANGED
    return None


def _pending_copy_retires() -> list[tuple[DoorCodeEvent, int]]:
    """``(duplicate_retire_pending event, copy id)`` for each one with no later ``duplicate_retire_done``."""
    pending: list[tuple[DoorCodeEvent, int]] = []
    events = (
        DoorCodeEvent.objects.filter(metadata__action=_COPY_RETIRE_PENDING, door_code__isnull=False)
        .select_related("door_code")
        .order_by("id")
    )
    for event in events:
        copy_id = _coerce_copy_id(event.metadata)
        if copy_id is None:
            continue
        if _copy_events_after(event=event, copy_id=copy_id, action=_COPY_RETIRE_DONE).exists():
            continue
        pending.append((event, copy_id))
    return pending


def _copy_events_after(*, event: DoorCodeEvent, copy_id: int, action: str):
    return DoorCodeEvent.objects.filter(
        door_code_id=event.door_code_id,
        metadata__action=action,
        metadata__duplicate_door_code_id=copy_id,
        id__gt=event.id,
    )


def pending_copy_retire_event_ids() -> set[int]:
    """The pending copy retires and their failed tries, which event retention keeps (PR #211 re-review)."""
    ids: set[int] = set()
    for event, copy_id in _pending_copy_retires():
        ids.add(event.id)
        ids.update(
            _copy_events_after(event=event, copy_id=copy_id, action=_COPY_RETIRE_FAILED).values_list("id", flat=True)
        )
    return ids


def retry_pending_copy_retires(*, zwavejs: ZwavejsGateway) -> int:
    """Try the copy retires :func:`retire_door_code` couldn't finish again, for the validity task (PR #211 review).

    A ``duplicate_retire_pending`` event with no later ``duplicate_retire_done``
    for the same copy on that retired code is tried again, and a
    ``duplicate_retire_done`` is written once it's retired (``outcome=retired``)
    or there's nothing left to do: ``outcome=gone`` when the copy was deleted,
    ``outcome=changed`` when it's off, dated, holds another PIN or isn't synced
    any more (issue #212). A copy someone has added a lock to since is flagged
    instead and gets ``outcome=left_alone``. Each try that raises leaves a ``duplicate_retire_failed``
    event, and once the first try and those reach ``door_codes.push_max_attempts``
    it gives up with one ``max_attempts_exceeded`` event (``action=duplicate_retire``)
    and a ``duplicate_retire_done`` with ``outcome=gave_up`` (PR #211
    re-review). That count is checked before each try too, so a cap of 1, or
    one lowered below the tries so far, gives up without another try (issue
    #212), but only for a copy that's still one to retire. One gone, changed
    or added to a lock since gets that outcome instead. The pending event goes with the retired code if that's
    deleted, and event retention keeps it while it's pending
    (:func:`pending_copy_retire_event_ids`). Returns how many it finished
    (retired, gone or changed).
    """
    from locks.use_cases.lock_push import _push_max_attempts

    max_attempts = _push_max_attempts()
    finished = 0
    for event, copy_id in _pending_copy_retires():
        where = {
            "original": event.door_code,
            "copy_id": copy_id,
            "lock_entity_id": event.lock_entity_id,
            "slot_index": int(event.metadata.get("slot_index") or 0),
        }
        # The retire's own try, then one per failed retry.
        tries = 1 + _copy_events_after(event=event, copy_id=copy_id, action=_COPY_RETIRE_FAILED).count()
        if max_attempts > 0 and tries >= max_attempts:
            # At the cap it only gives up on a copy that's still one to retire,
            # without a try, so a copy gone or changed meanwhile says so (PR #228 review).
            outcome = _copy_not_a_candidate(copy=DoorCode.objects.filter(id=copy_id).first(), original=event.door_code)
            if not outcome:
                _give_up_copy_retire(event=event, copy_id=copy_id, tries=tries, where=where)
                continue
        else:
            outcome = _retire_synced_copy(copy_id=copy_id, original=event.door_code, zwavejs=zwavejs)
        if outcome == _COPY_LEFT_ALONE:
            # Someone added a lock to it since, so it's not a stranded copy any
            # more (:func:`_is_stranded_copy`) and is only flagged.
            _flag_surviving_duplicate(**where)
            _record_copy_event(action=_COPY_RETIRE_DONE, outcome=_COPY_LEFT_ALONE, **where)
            continue
        if outcome:
            _record_copy_event(action=_COPY_RETIRE_DONE, outcome=outcome, **where)
            finished += 1
            continue
        _record_copy_event(action=_COPY_RETIRE_FAILED, **where)
        tries += 1
        if max_attempts > 0 and tries >= max_attempts:
            _give_up_copy_retire(event=event, copy_id=copy_id, tries=tries, where=where)
    return finished


def _give_up_copy_retire(*, event: DoorCodeEvent, copy_id: int, tries: int, where: dict) -> None:
    """End a pending copy retire at ``door_codes.push_max_attempts`` with one ``max_attempts_exceeded`` event."""
    logger.warning(
        "Giving up retiring synced door code id=%d, a copy of retired door code id=%d's PIN, after %d tries",
        copy_id,
        event.door_code_id,
        tries,
    )
    DoorCodeEvent.objects.create(
        door_code=event.door_code,
        user=None,
        lock_entity_id=event.lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": "duplicate_retire",
            "reason": "max_attempts_exceeded",
            "attempts": tries,
            "duplicate_door_code_id": copy_id,
        },
    )
    _record_copy_event(action=_COPY_RETIRE_DONE, outcome="gave_up", **where)


def _coerce_copy_id(metadata: object) -> int | None:
    value = metadata.get("duplicate_door_code_id") if isinstance(metadata, dict) else None
    return value if isinstance(value, int) else None


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

    A withdraw with a failure left (a clear that failed, or a readback with no
    answer, which isn't recorded) counts one attempt on the code's clear-retry
    count like the #167 inactive clear, and a code at
    ``door_codes.push_max_attempts`` isn't withdrawn again, so its rollup is
    ``failed`` until Retry resets the count (PR #207 review). The withdraw
    that takes the count to the cap writes one ``max_attempts_exceeded``
    event. The ``withdrawn`` event is only written when a slot was cleared.

    Checked once before the locks are taken too, so a code with nothing left to
    withdraw (its slots already cleared or left to the clear retries) doesn't
    hold every lock it's on each tick and make a push there wait (PR #183 review).
    """
    from locks.use_cases.lock_push import (
        _push_max_attempts,
        refresh_push_state,
        slots_to_withdraw,
        withdraw_slots_before_start,
    )

    def nothing_to_withdraw() -> bool:
        check_at = now if now is not None else django_timezone.now()
        max_attempts = _push_max_attempts()
        return (
            not code.is_active
            or is_started(code, now=check_at)
            or (max_attempts > 0 and (code.push_attempt_count or 0) >= max_attempts)
            or not slots_to_withdraw(door_code=code)
        )

    if nothing_to_withdraw():
        return False
    try:
        with _hold_door_code_locks(code=code):
            if nothing_to_withdraw():
                return False
            cleared, failures = withdraw_slots_before_start(door_code=code, zwavejs=zwavejs)
            transient = [f for f in failures if not f.permanent]
            if transient:
                # Counted like the #167 inactive clear, so a slot that keeps not
                # answering hits the cap instead of being read back every tick.
                attempted_at = django_timezone.now()
                DoorCode.objects.filter(id=code.id).update(
                    push_attempt_count=F("push_attempt_count") + 1,
                    last_push_attempt_at=attempted_at,
                    updated_at=attempted_at,
                )
                _record_withdraw_gave_up(code=code, failure=transient[0], max_attempts=_push_max_attempts())
            # Off its locks until it starts, so it's pending (scheduled), or
            # failed once its clears hit the cap (issue #126). Each lock it
            # cleared went back to pending through forget_cleared_slot. A
            # readback with no answer left no event, so it's passed in to show
            # in the error.
            refresh_push_state(door_code=code, unrecorded_failures=failures)
            if not cleared:
                return True
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


def _refuse_duplicate_pin_when_turning_on(*, code: DoorCode, changes: dict) -> None:
    """Raise :class:`DuplicatePinOnLock` when turning ``code`` on would put its PIN in a second slot (issue #188).

    Someone can type a retired code's PIN back in at the keypad, and lock sync
    then imports it as a new "Slot N" code. Turning the retired code back on
    would push the same PIN into another slot. So turning a code on is refused
    while another code on one of its locks (the ones it's being saved with) has
    the same PIN in a slot there, or is active there and waiting for its push.
    It compares the PIN being saved, so changing the PIN in the same save gets
    past it. It refuses rather than adopting the other code's slot, since that
    code may be one someone added on purpose (2 codes can share a PIN), and
    adopting it would take its slot and its history away without asking. The
    error names the lock, the slot and the other code so it can be deleted.
    """
    if not changes.get("is_active") or code.is_active:
        return
    from locks.use_cases.lock_push import decrypt_pin_or_none

    pin = str(changes["code"]).strip() if changes.get("code") else decrypt_pin_or_none(code)
    if not pin:
        return
    # The locks it's being saved with, so a lock added in the same save counts
    # and one still being removed doesn't (issues #159, #171).
    _refuse_pin_held_on_locks(
        code=code, pin=pin, lock_entity_ids=_locks_after_save(code=code, changes=changes), before="turning it on"
    )


def _refuse_duplicate_pin_on_added_locks(*, code: DoorCode, changes: dict) -> None:
    """Raise :class:`DuplicatePinOnLock` when a lock added to a code already has its PIN (issue #188).

    The push to the added lock would put the PIN in a second slot there, the
    same as turning a code on, so it's the same check on the added locks only.
    A manual code that's being turned on in this save is checked on all its
    locks by :func:`_refuse_duplicate_pin_when_turning_on`, and an inactive
    one isn't pushed anywhere until that check runs. A synced code is checked
    whether it's on or off: lock sync is what turns an undated one back on,
    and lock sync never runs that check.
    """
    synced = code.source == DoorCode.Source.SYNCED
    if not synced and (not code.is_active or ("is_active" in changes and not changes["is_active"])):
        return
    added = _added_locks(code=code, changes=changes)
    if not added:
        return
    from locks.use_cases.lock_push import decrypt_pin_or_none

    pin = str(changes["code"]).strip() if changes.get("code") else decrypt_pin_or_none(code)
    if not pin:
        return
    _refuse_pin_held_on_locks(code=code, pin=pin, lock_entity_ids=added, before="adding that lock")


def _refuse_pin_held_on_locks(*, code: DoorCode, pin: str, lock_entity_ids: list[str], before: str) -> None:
    """Raise :class:`DuplicatePinOnLock` when another code on one of ``lock_entity_ids`` has ``pin`` (issue #188).

    That's a code holding it in a slot there, or one active there and waiting
    for its push. The error names the lock, the slot and the other code, never the PIN.
    """
    from locks.use_cases.lock_push import decrypt_pin_or_none

    others = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(lock_entity_id__in=lock_entity_ids)
        .exclude(door_code=code)
        .order_by("lock_entity_id", "door_code_id")
    )
    for assignment in others:
        other = assignment.door_code
        if assignment.slot_index is None and not other.is_active:
            continue
        if decrypt_pin_or_none(other) != pin:
            continue
        name = f'door code {other.id} ("{other.label}")' if other.label else f"door code {other.id}"
        where = f"in slot {assignment.slot_index}" if assignment.slot_index is not None else "waiting to be pushed"
        # A synced code's PIN is the lock's, so deleting the other code is the only way.
        if code.source == DoorCode.Source.SYNCED:
            fix = "Delete that code"
        else:
            fix = "Delete that code or give this one a different PIN"
        raise DuplicatePinOnLock(
            f"{assignment.lock_entity_id} already has this PIN {where} as {name}. {fix} before {before}."
        )


def _has_lock_changes(changes: dict) -> bool:
    """Whether the update sends ``add_lock_entity_ids`` / ``remove_lock_entity_ids`` (issue #159)."""
    return "add_lock_entity_ids" in changes or "remove_lock_entity_ids" in changes


# Written only by the keypad use count (``locks.use_cases.code_usage``) with
# ``F()``. An update's save leaves them alone, since the code it holds was read
# before a use may have landed (issue #145).
_USAGE_FIELDS = frozenset({"uses_count", "last_used_at", "last_used_lock"})


def _save_unless_deleted(code: DoorCode) -> None:
    """Save ``code``, raising :class:`NotFound` if it was deleted meanwhile (issue #189).

    A plain ``save()`` on a row that's gone inserts it again. The code row is
    taken first, like every writer of it, so a delete can't land between the
    check and the write. Every field but :data:`_USAGE_FIELDS` is written, and
    those are read back from the row so ``code`` has the current count.
    """
    fields = [f.name for f in DoorCode._meta.concrete_fields if not f.primary_key and f.name not in _USAGE_FIELDS]
    with transaction.atomic():
        if DoorCode.objects.select_for_update().filter(id=code.id).first() is None:
            raise NotFound("Not found.")
        code.save(update_fields=fields)
        code.refresh_from_db(fields=sorted(_USAGE_FIELDS))


def _locks_after_save(*, code: DoorCode, changes: dict) -> list[str]:
    """The locks ``code`` is on once this save lands, without the ones still being removed.

    The full ``lock_entity_ids`` when it's sent. With ``add_lock_entity_ids`` /
    ``remove_lock_entity_ids`` (issue #159) the code's locks now, less the
    removed ones and the ones whose removal is still waiting on its clear
    (issue #171), plus the added ones, which is how a re-added one comes back.
    Otherwise the code's locks without those still being removed.
    """
    if "lock_entity_ids" in changes:
        return list(dict.fromkeys(changes.get("lock_entity_ids") or []))
    from locks.use_cases.lock_push import unresolved_clear_failures

    removing = {f.lock_entity_id for f in unresolved_clear_failures(door_code=code) if f.removing}
    removed = set(changes.get("remove_lock_entity_ids") or [])
    current = (
        DoorCodeLockAssignment.objects.filter(door_code=code).order_by("pk").values_list("lock_entity_id", flat=True)
    )
    kept = [lock for lock in current if lock not in removing and lock not in removed]
    return list(dict.fromkeys([*kept, *(changes.get("add_lock_entity_ids") or [])]))


def _refuse_lock_changes_leaving_no_locks(*, code: DoorCode, changes: dict) -> None:
    """Raise :class:`DoorCodeWouldHaveNoLocks` when the save's lock removals would leave ``code`` on no lock.

    Only for ``add_lock_entity_ids`` / ``remove_lock_entity_ids``. A full
    ``lock_entity_ids: []`` is still taken for a manual code, as it always
    was, but not for a synced one: the door codes list leaves out a synced code
    with no locks, so it would be gone from the page while its row stays.
    Checked before anything changes. A code with a lock is only saved while
    that lock's ``lock_sync:`` lock is held, so two removals can't both pass this.
    """
    removes = bool(changes.get("remove_lock_entity_ids")) or (
        code.source == DoorCode.Source.SYNCED and "lock_entity_ids" in changes
    )
    if removes and not _locks_after_save(code=code, changes=changes):
        raise DoorCodeWouldHaveNoLocks("This save would leave the code with no locks.")


def _added_locks(*, code: DoorCode, changes: dict) -> list[str]:
    """The locks this save puts ``code`` on that it has no assignment on yet, so a push goes to them.

    A lock still being removed keeps its assignment, so adding it back only
    cancels the removal and isn't counted.
    """
    current = set(DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", flat=True))
    return [lock for lock in _locks_after_save(code=code, changes=changes) if lock not in current]


def _refuse_adding_locks_without_pin(*, code: DoorCode, changes: dict) -> None:
    """Raise :class:`DoorCodePinUnknown` when this save adds a lock to a code without a readable PIN.

    A synced code imported from a lock that masks its codes has no stored PIN,
    and one whose stored PIN can't be decrypted is no better, so there's
    nothing to push to the new lock. That goes for any source: a synced code
    made manual once it lost its import lock (issue #222) keeps whatever PIN it
    had. A new PIN in the same save is the one pushed, so that's fine. Removing
    locks is still fine, since a clear doesn't need the PIN.
    """
    if changes.get("code") or not _added_locks(code=code, changes=changes):
        return
    from locks.use_cases.lock_push import decrypt_pin_or_none

    if decrypt_pin_or_none(code) is None:
        # A synced code's PIN comes from the lock, so only a manual code can be given a new one here.
        why = (
            "Either the lock it was synced from hides its codes or the stored PIN can't be decrypted."
            if code.source == DoorCode.Source.SYNCED
            else "Give it a new PIN in the same save and that one goes on the lock."
        )
        raise DoorCodePinUnknown(
            f"Latchpoint doesn't have a readable PIN for this code, so it can't put it on another lock. {why}"
        )


def _record_withdraw_gave_up(*, code: DoorCode, failure: ClearFailure, max_attempts: int) -> None:
    """One ``max_attempts_exceeded`` event when the withdraw's count just reached the cap (PR #207 review).

    A code at the cap isn't withdrawn again until Retry resets the count, so
    this is written once each time it gets there. No PIN goes in it.
    """
    from locks.use_cases.lock_push import sanitize_push_error_for_storage

    attempts = DoorCode.objects.filter(id=code.id).values_list("push_attempt_count", flat=True).first()
    if max_attempts <= 0 or attempts is None or attempts < max_attempts:
        return
    DoorCodeEvent.objects.create(
        door_code=code,
        user=None,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": "withdraw",
            "reason": "max_attempts_exceeded",
            "attempts": attempts,
            "last_error": sanitize_push_error_for_storage(failure.reason)[:200],
        },
    )


# ``source_changed.reason`` on the ``code_updated`` event of a synced code made manual (issue #222).
_CONVERTED_NO_IMPORT_LOCK = "no_import_lock"


def _convert_when_no_import_lock(*, code: DoorCode, added_lock_entity_ids: list[str]) -> list[str]:
    """Make a synced code manual once no lock it's on is one lock sync imported it from (issue #222).

    A synced code's PIN, active flag and schedule come only from its import lock
    (ADR 0082). Lock sync treats every slot latchpoint pushed like a manual
    code's, so with the import lock removed (or being removed), or removed and
    added back (which makes it a pushed lock), nothing would ever change them
    and the edit form would keep them read-only. Latchpoint is the only one
    pushing the code then, so it's a manual code from here on, which lock sync
    keeps manual (#166, #214).

    The import locks are :func:`~locks.use_cases.lock_push.import_lock_entity_ids`
    less the locks this save added. A code with no locks at all is left as it
    is. A permanent code with dates becomes temporary, since a manual code only
    has dates as temporary (or one-time) and couldn't change them otherwise.
    Saved under the code row like every writer of it. Returns the fields
    changed, ``[]`` when it stays synced.
    """
    from locks.use_cases.lock_push import import_lock_entity_ids

    if code.source != DoorCode.Source.SYNCED:
        return []
    if not DoorCodeLockAssignment.objects.filter(door_code=code).exists():
        return []
    if import_lock_entity_ids(door_code=code, exclude=added_lock_entity_ids):
        return []
    fields = ["source"]
    code.source = DoorCode.Source.MANUAL
    if code.code_type == DoorCode.CodeType.PERMANENT and (code.start_at is not None or code.end_at is not None):
        code.code_type = DoorCode.CodeType.TEMPORARY
        fields.append("code_type")
    with transaction.atomic():
        if DoorCode.objects.select_for_update().filter(id=code.id).first() is None:
            raise NotFound("Not found.")
        DoorCode.objects.filter(id=code.id).update(
            source=code.source, code_type=code.code_type, updated_at=django_timezone.now()
        )
    logger.info("Door code id=%d has no import lock left; it's a manual code now", code.id)
    return fields


def _record_unread_added_slot(
    *, code: DoorCode, assignment: DoorCodeLockAssignment, written: str | None, pin: str | None, exc: Exception
) -> ClearFailure:
    """Record a synced code's added-lock slot whose read before a clear got no answer (#223's rule).

    With what latchpoint wrote there recorded, the slot is let go and recorded as
    an unconfirmed clear expecting that PIN (or a masked code), so the scheduler's
    retry reads it back before it clears anything and never clears blind. With
    nothing recorded (a lock pushed before 0012) the slot may hold any older PIN
    of latchpoint's, so it stays tracked with a plain clear failure and the retry
    clears it the way a delete clears a slot like that. A lock latchpoint can't
    resolve any more is forgotten as ``lock_missing``. Used by the #222
    conversion and by delete (issue #221).
    """
    from locks.use_cases.lock_push import forget_cleared_slot, record_clear_failure

    slot_index = int(assignment.slot_index)
    lock_entity_id = assignment.lock_entity_id
    if written is None:
        failure = record_clear_failure(
            door_code=code, lock_entity_id=lock_entity_id, slot_index=slot_index, exc=exc, expected_pin=pin
        )
    else:
        failure = record_clear_failure(
            door_code=code,
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            exc=exc,
            expected_pin=written,
            unconfirmed=True,
            slot_verified=True,
        )
    if failure.permanent:
        forget_cleared_slot(
            door_code=code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
        )
    elif written is not None:
        DoorCodeLockAssignment.objects.filter(id=assignment.id).update(
            slot_index=None,
            written_pin=None,
            written_schedule=None,
            schedule_pending=False,
            push_state=DoorCode.PushState.PENDING,
        )
    return failure


def _clear_locks_behind_after_conversion(*, code: DoorCode, zwavejs: ZwavejsGateway) -> list[ClearFailure]:
    """Hand a converted code's added locks to the manual push paths (issue #222). Returns the clears that failed.

    Lock sync of the import lock flagged the added locks for their reconcile
    when it took a new PIN or schedule (issue #220), and a lock still flagged
    (or recorded as holding another PIN or schedule than the code's,
    :func:`~locks.use_cases.added_lock_reconcile.lock_behind_code`) may still
    hold the older one. So it's cleared and pushed again: slots an unconfirmed
    push may have left a PIN in are read back and cleared when they hold it,
    and the tracked slot is read back with the reconcile's and the delete's
    rule (:func:`~locks.use_cases.added_lock_reconcile.read_added_slot`). It's
    cleared when it holds the code's PIN, the PIN latchpoint wrote there or a
    code the lock won't show (or any user code when nothing is recorded), and
    let go untouched when it holds someone else's PIN or nothing. Either way
    the lock goes back to pending and the push puts the code in a free slot. A
    clear that fails is recorded for the scheduler's retries and keeps the
    slot, like an edit's. A read with no answer lets the slot go and records it
    as an unconfirmed clear expecting the PIN latchpoint wrote there, so the
    retry reads it back before it clears anything. When nothing is recorded
    there the slot stays tracked with a plain clear failure instead, so the
    retry clears it like a delete would. A lock where another code already has
    the PIN is failed with :func:`~locks.use_cases.added_lock_reconcile.held_pin_error`
    once its slot is off it, not pushed (issue #188). Every flag on the code is
    dropped, so nothing is left for the reconcile and nothing writes to these
    locks twice. A lock the code is being dropped from is left to its clear.
    The caller holds every lock the code is on.
    """
    from locks.use_cases.added_lock_reconcile import (
        _let_go,
        held_pin_error,
        lock_behind_code,
        pin_held_by_another_code,
        read_added_slot,
        slot_is_latchpoints,
    )
    from locks.use_cases.lock_config_sync import _resolve_lock_node_id, clear_lock_user_code_slot
    from locks.use_cases.lock_push import (
        _lock_code_row,
        _locks_being_removed,
        clear_unconfirmed_slots_holding_pin,
        code_schedule_fingerprint,
        decrypt_pin_or_none,
        forget_cleared_slot,
        record_clear_failure,
    )

    pin = decrypt_pin_or_none(code)
    desired = code_schedule_fingerprint(code)
    removing = _locks_being_removed(door_code=code)
    behind = [
        a
        for a in DoorCodeLockAssignment.objects.filter(door_code=code).order_by("lock_entity_id")
        if a.lock_entity_id not in removing and lock_behind_code(a, pin=pin, desired=desired)
    ]
    failures: list[ClearFailure] = []
    if behind:
        _, unconfirmed_failures = clear_unconfirmed_slots_holding_pin(
            door_code=code, pin=pin or "", lock_entity_ids=[a.lock_entity_id for a in behind], zwavejs=zwavejs
        )
        failures.extend(unconfirmed_failures)
    for assignment in behind:
        if assignment.slot_index is None:
            continue
        slot_index = int(assignment.slot_index)
        lock_entity_id = assignment.lock_entity_id
        # What latchpoint last wrote there, when it's recorded.
        written = (
            decrypt_pin_or_none(DoorCode(encrypted_pin=assignment.written_pin)) if assignment.written_pin else None
        )
        try:
            verdict = read_added_slot(
                zwavejs=zwavejs,
                node_id=_resolve_lock_node_id(lock_entity_id=lock_entity_id),
                slot_index=slot_index,
                pin=pin,
                written_pin=written,
                timeout_seconds=_REQUEST_CLEAR_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            failures.append(
                _record_unread_added_slot(code=code, assignment=assignment, written=written, pin=pin, exc=exc)
            )
            continue
        if not slot_is_latchpoints(verdict):
            # Someone else's PIN (typed in at the keypad, say) or nothing: left as it
            # is, and the code is pushed into a free slot.
            _let_go(code=code, assignment=assignment, empty=verdict == "empty")
            continue
        try:
            clear_lock_user_code_slot(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                zwavejs=zwavejs,
                timeout_seconds=_REQUEST_CLEAR_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            failure = record_clear_failure(
                door_code=code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                exc=exc,
                expected_pin=written or pin,
            )
            failures.append(failure)
            if not failure.permanent:
                # It was just read back as latchpoint's, so it stays tracked
                # until a retry clears it (issue #139).
                continue
            outcome = "lock_missing"
        else:
            outcome = "cleared"
        forget_cleared_slot(door_code=code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome=outcome)
    with transaction.atomic():
        _lock_code_row(code.id)
        DoorCodeLockAssignment.objects.filter(door_code=code, reconcile_requested_at__isnull=False).update(
            reconcile_requested_at=None
        )
        if behind:
            # A fresh start, without the reconcile's "Waiting to send…" error.
            DoorCodeLockAssignment.objects.filter(id__in=[a.id for a in behind]).update(
                push_attempt_count=0, last_push_error=""
            )
        # The #188 rule, like the reconcile: a lock where another code already
        # has the PIN isn't pushed, it's failed for a human once its old PIN is
        # off. One whose slot is still tracked (its clear failed) waits for that.
        for row in DoorCodeLockAssignment.objects.filter(id__in=[a.id for a in behind], slot_index__isnull=True):
            holder = pin_held_by_another_code(door_code=code, lock_entity_id=row.lock_entity_id, pin=pin)
            if holder is not None:
                DoorCodeLockAssignment.objects.filter(id=row.id).update(
                    push_state=DoorCode.PushState.FAILED, push_attempt_count=0, last_push_error=held_pin_error(holder)
                )
    return failures


def _update_door_code_locked(
    *,
    code: DoorCode,
    changes: dict,
    actor_user: User | None = None,
    zwavejs: ZwavejsGateway | None = None,
    event_metadata: dict[str, object] | None = None,
    convert_without_import_lock: bool = False,
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

    ``add_lock_entity_ids`` / ``remove_lock_entity_ids`` (issue #159) only add
    and drop the locks they name, against the assignments read once in the
    diff below, so a lock another save added meanwhile is never dropped by
    this one, and a lock still being removed stays that way unless it's added
    again. Removals that would leave no lock are refused before anything
    changes, and so are added locks when the code's PIN isn't known or another
    code already has it on an added lock (issue #188). That goes for synced
    codes too, whose locks are edited the same way (ADR 0082). A code deleted
    meanwhile is a :class:`NotFound`, never saved back.

    With ``convert_without_import_lock`` (a user's edit, not a retire) a synced
    code whose lock changes in this save leave it no import lock becomes a
    manual code (issue #222, :func:`_convert_when_no_import_lock`), and its added locks
    that may be behind its PIN or schedule are cleared and pushed again
    (:func:`_clear_locks_behind_after_conversion`).
    """
    _refuse_lock_changes_leaving_no_locks(code=code, changes=changes)
    _refuse_adding_locks_without_pin(code=code, changes=changes)
    _refuse_duplicate_pin_when_turning_on(code=code, changes=changes)
    _refuse_duplicate_pin_on_added_locks(code=code, changes=changes)
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

    _save_unless_deleted(code)

    # Diff the lock set. Locks that stay keep their assignment and slot_index;
    # recreating them would forget a slot the lock still holds the PIN in, and the
    # re-push would write it into a second slot (issue #133).
    dropped_lock_entity_ids: list[str] = []
    removed_lock_entity_ids: list[str] = []
    added_lock_entity_ids: list[str] = []
    failed_slot_clears: list[ClearFailure] = []
    # A full lock_entity_ids always counts as a lock change, like before. Adds and
    # removes only when they change something (issue #159).
    locks_changed = "lock_entity_ids" in changes
    if locks_changed or _has_lock_changes(changes):
        old_assignments = list(DoorCodeLockAssignment.objects.filter(door_code=code))
        old_entity_ids = {assignment.lock_entity_id for assignment in old_assignments}
        if locks_changed:
            new_entity_ids = list(dict.fromkeys(changes.get("lock_entity_ids") or []))
            keeping_cancels_removal = set(new_entity_ids)
        else:
            # Only the named locks, against this one read, so a lock another
            # save added meanwhile stays and one being removed is left to its
            # clear unless it's added again.
            added = list(dict.fromkeys(changes.get("add_lock_entity_ids") or []))
            removed = set(changes.get("remove_lock_entity_ids") or [])
            new_entity_ids = [
                *(a.lock_entity_id for a in old_assignments if a.lock_entity_id not in removed),
                *(lock for lock in added if lock not in old_entity_ids),
            ]
            keeping_cancels_removal = set(added)
            from locks.use_cases.lock_push import unresolved_clear_failures

            removing = {f.lock_entity_id for f in unresolved_clear_failures(door_code=code) if f.removing}
            locks_changed = bool(
                old_entity_ids & removed
                or set(added) - old_entity_ids
                or (zwavejs is not None and set(added) & removing)
            )
        removed_assignment_ids: list[int] = []
        for assignment in old_assignments:
            if assignment.lock_entity_id in new_entity_ids:
                if zwavejs is not None and assignment.lock_entity_id in keeping_cancels_removal:
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
            with transaction.atomic():
                # The code row first, so a delete that ran meanwhile is a 404
                # rather than assignments for a code that's gone.
                if DoorCode.objects.select_for_update().filter(id=code.id).first() is None:
                    raise NotFound("Not found.")
                # Stamped as queued even when the code is off or not started and
                # nothing pushes it yet, so a lock added in latchpoint is never
                # taken for one lock sync imported the code from (issue #222).
                # The queued push task only picks it up once the code belongs on
                # its locks, and the request lapses like any other.
                added_at = django_timezone.now()
                DoorCodeLockAssignment.objects.bulk_create(
                    [
                        DoorCodeLockAssignment(
                            door_code=code,
                            lock_entity_id=entity_id,
                            push_requested_at=added_at,
                        )
                        for entity_id in added_lock_entity_ids
                    ],
                    ignore_conflicts=True,
                )
        if locks_changed:
            updated_fields.append("lock_entity_ids")

    # Only on a save that adds or drops a lock (a full list that names the same
    # locks doesn't count), under every lock the code is on, so no lock sync or
    # reconcile runs on them while it changes. Needs the gateway for the clears
    # it may take.
    converted_fields: list[str] = []
    if convert_without_import_lock and (added_lock_entity_ids or dropped_lock_entity_ids) and zwavejs is not None:
        converted_fields = _convert_when_no_import_lock(code=code, added_lock_entity_ids=added_lock_entity_ids)
        updated_fields.extend(converted_fields)

    updated_event: DoorCodeEvent | None = None
    if updated_fields:
        metadata: dict[str, object] = {"updated_fields": updated_fields, **(event_metadata or {})}
        if added_lock_entity_ids:
            metadata["added_lock_entity_ids"] = sorted(added_lock_entity_ids)
        if removed_lock_entity_ids:
            metadata["removed_lock_entity_ids"] = sorted(removed_lock_entity_ids)
        if converted_fields:
            metadata["source_changed"] = {
                "from": DoorCode.Source.SYNCED,
                "to": DoorCode.Source.MANUAL,
                "reason": _CONVERTED_NO_IMPORT_LOCK,
            }
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

        if converted_fields:
            failed_slot_clears.extend(_clear_locks_behind_after_conversion(code=code, zwavejs=zwavejs))

        push_relevant_change = bool(push_trigger_changes)
        if push_relevant_change or locks_changed or converted_fields:
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
    if zwavejs is not None or locks_changed:
        from locks.use_cases.lock_push import refresh_push_state

        refresh_push_state(door_code=code)

    return code, push_inline


def door_codes_on_locks(*, users) -> QuerySet[DoorCode]:
    """The ``users``' door codes that are on a lock, ie have a lock assignment (issue #235).

    Deleting a user cascades their door codes without :func:`delete_door_code`,
    so nothing clears them off the locks and their PINs keep opening the doors
    untracked. These codes keep the user from being deleted until they're
    deleted the normal way. A code with no assignment can still cascade.
    """
    return DoorCode.objects.filter(user__in=users, lock_assignments__isnull=False).distinct().order_by("id")


def user_delete_refused_message(users) -> str:
    """Why ``users`` can't be deleted while :func:`door_codes_on_locks` has codes for them."""
    names = ", ".join(sorted(str(user) for user in users))
    return (
        f"Can't delete {names}: they still have door codes on a lock. "
        "Delete their door codes first, which clears them off the locks, then delete the user."
    )


def refuse_deleting_user_with_door_codes_on_locks(sender, instance, **kwargs) -> None:  # noqa: ARG001
    """``pre_delete`` receiver for ``User``: raise ``ProtectedError`` while they have door codes on a lock (issue #235).

    Covers every ORM delete (``user.delete()``, ``QuerySet.delete()``). Django
    sends ``pre_delete`` inside the delete's transaction before deleting
    anything, so the raise leaves every user and code in place. That
    transaction has no savepoint, so inside an outer ``atomic`` the raise
    breaks it unless the delete has its own ``atomic``. The Django admin
    refuses before it gets here (``accounts.admin.UserAdmin``).
    """
    codes = list(door_codes_on_locks(users=[instance]))
    if codes:
        raise ProtectedError(user_delete_refused_message([instance]), set(codes))


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

    A synced code is deleted the way a manual code is when latchpoint has ever
    pushed or queued a push of it to any lock (an assignment with
    ``last_push_attempt_at`` or ``push_requested_at``, which also covers rows
    migration 0010 stamped from the code's last attempt and a dated synced code
    turned back on, #189), or when it still has a clear failure or an
    unconfirmed push attempt on record, on a lock it's still on or one it was
    removed from. Any of those can leave its PIN in a slot only latchpoint
    knows about, ie an added lock's unconfirmed push (ADR 0082). A fail-fast
    raise after the first lock's clear would leave the row saying that slot is
    still held with nothing recorded to retry, and a delete that went ahead
    would take the clear failure or attempt with it and leave the PIN on the
    lock untracked. Any other synced code keeps the fail-fast.
    """
    from locks.use_cases.lock_push import (
        has_lock_pushed_by_latchpoint,
        slot_pushed_by_latchpoint,
        unconfirmed_attempt_lock_entity_ids,
        unresolved_clear_failures,
    )

    code_id = code.id
    label = code.label
    user = code.user
    extra_metadata: dict[str, object] = {}
    # Whether the delete refuses and records failed clears, like a manual code's.
    manual = (
        code.source != DoorCode.Source.SYNCED
        or has_lock_pushed_by_latchpoint(door_code_id=code.id)
        or bool(unresolved_clear_failures(door_code=code))
        or bool(unconfirmed_attempt_lock_entity_ids(door_code=code))
    )
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
            # A synced code's added locks (issue #220): only a PIN latchpoint put in the slot is cleared.
            added = {
                (a.lock_entity_id, int(a.slot_index)): a
                for a in assignments
                if code.source == DoorCode.Source.SYNCED and a.slot_index is not None and slot_pushed_by_latchpoint(a)
            }
            for slot_info in slots_to_clear:
                if (slot_info["lock_entity_id"], slot_info["slot_index"]) in already_failed:
                    continue  # its retry above just failed
                added_assignment = added.get((slot_info["lock_entity_id"], slot_info["slot_index"]))
                if added_assignment is not None:
                    try:
                        latchpoints = _added_slot_is_latchpoints(
                            code=code, assignment=added_assignment, zwavejs=zwavejs
                        )
                    except Exception as exc:
                        # No verdict: recorded so the scheduler's retry reads the slot
                        # back before it clears it, not blind (issue #221).
                        written = (
                            decrypt_pin_or_none(DoorCode(encrypted_pin=added_assignment.written_pin))
                            if added_assignment.written_pin
                            else None
                        )
                        failure = _record_unread_added_slot(
                            code=code,
                            assignment=added_assignment,
                            written=written,
                            pin=decrypt_pin_or_none(code),
                            exc=exc,
                        )
                        (permanent_failures if failure.permanent else transient_failures).append(failure)
                        continue
                    if not latchpoints:
                        # Someone else's PIN, or nothing: left as it is.
                        extra_metadata.setdefault("left_slots", []).append(slot_info)
                        continue
                try:
                    clear_lock_user_code_slot(
                        lock_entity_id=slot_info["lock_entity_id"],
                        slot_index=slot_info["slot_index"],
                        zwavejs=zwavejs,
                        timeout_seconds=_REQUEST_CLEAR_TIMEOUT_SECONDS,
                    )
                    cleared.append(slot_info)
                except Exception as exc:
                    if not manual:
                        # Synced codes on their import lock only still fail-fast (ADR 0082 contract).
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

    from locks.use_cases.lock_push import keep_slot_empty_markers_of_deleted_code

    with transaction.atomic():
        # The code row first. code.delete() deletes the assignments before the
        # code row, and the scheduler's cap sweep takes the code row then its
        # assignments, so without this the two can deadlock (PR #195 review).
        DoorCode.objects.select_for_update().filter(id=code.id).first()
        # Its empty readbacks still drop other codes' masked-slot trust (issue #194).
        keep_slot_empty_markers_of_deleted_code(door_code=code)
        DoorCodeEvent.objects.create(
            door_code=None,
            user=actor_user,
            event_type=DoorCodeEvent.EventType.CODE_DELETED,
            metadata={"code_id": code_id, "label": label, "user_id": str(user.id), **extra_metadata},
        )

        code.delete()


def _added_slot_is_latchpoints(*, code: DoorCode, assignment: DoorCodeLockAssignment, zwavejs: ZwavejsGateway) -> bool:
    """Whether a synced code's added-lock slot holds a PIN latchpoint put there, so a delete clears it (issue #220).

    Read live: the code's PIN, the one latchpoint last wrote there or a code the
    lock won't show count, and another PIN or an empty slot doesn't, the same
    rule :func:`locks.use_cases.added_lock_reconcile.reconcile_added_lock` uses.
    A read that gets no answer raises, and the delete records it with
    :func:`_record_unread_added_slot`, so the retry reads it back first (issue #221).
    """
    from locks.use_cases.added_lock_reconcile import read_added_slot, slot_is_latchpoints
    from locks.use_cases.lock_config_sync import _resolve_lock_node_id
    from locks.use_cases.lock_push import decrypt_pin_or_none

    written = None
    if assignment.written_pin:
        written = decrypt_pin_or_none(DoorCode(encrypted_pin=assignment.written_pin))
    verdict = read_added_slot(
        zwavejs=zwavejs,
        node_id=_resolve_lock_node_id(lock_entity_id=assignment.lock_entity_id),
        slot_index=int(assignment.slot_index),
        pin=decrypt_pin_or_none(code),
        written_pin=written,
        timeout_seconds=_REQUEST_CLEAR_TIMEOUT_SECONDS,
    )
    return slot_is_latchpoints(verdict)


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


# On each pending lock with no error of its own when queueing its push failed (issue #203).
_QUEUE_FAILED_ERROR = "Couldn't queue the push (see backend logs), the scheduler will retry it"


def _request_push_best_effort(*, code: DoorCode, actor_user: User | None) -> None:
    """Queue the code's push (:func:`locks.use_cases.lock_push.request_push`) without raising into the API path.

    The save already happened, so a DB error queueing it doesn't fail the
    request, the same as :func:`_push_to_assigned_locks_best_effort`. The locks
    stay pending for the scheduler's 300s retry (PR #201 review), and each
    pending one with no error of its own says why in ``last_push_error``. Any
    other error is a bug, so it's raised in dev and tests like
    ``PushInTransaction`` and handled the same way in prod (issue #203).
    """
    try:
        from locks.use_cases.lock_push import request_push

        request_push(code, actor_user=actor_user)
    except Exception as exc:
        _raise_unless_db_error_in_prod(exc)
        logger.exception("Couldn't queue the push of door code id=%s; leaving it to the scheduler's retry", code.id)
    else:
        return
    try:
        from locks.use_cases.lock_push import refresh_push_state

        DoorCodeLockAssignment.objects.filter(
            door_code_id=code.id, push_state=DoorCode.PushState.PENDING, last_push_error=""
        ).update(last_push_error=_QUEUE_FAILED_ERROR)
        refresh_push_state(door_code=code)
    except Exception as exc:
        _raise_unless_db_error_in_prod(exc)
        logger.exception("Couldn't record the failed queue of door code id=%s", code.id)


def _raise_unless_db_error_in_prod(exc: Exception) -> None:
    """Re-raise ``exc`` in dev and tests unless it's a DB error, like ``PushInTransaction`` (issue #203)."""
    if not isinstance(exc, DbError) and (settings.DEBUG or getattr(settings, "IS_TESTING", False)):
        raise exc


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
    (issue #158), or for a synced code an added lock its import lock confirmed
    it off for (issue #221), and is never pushed.

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
        # Deleted while the Retry ran is a 404, not a DoesNotExist 500 (issue #189).
        return get_door_code_for_read(code_id=code.id)

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

    from locks.use_cases.added_lock_reconcile import off_clear_lock_entity_ids

    if (
        not code.is_active
        and not unresolved_clear_failures(door_code=code)
        and not inactive_slots_to_clear(door_code=code)
        and not off_clear_lock_entity_ids(door_code=code)
    ):
        if code.source == DoorCode.Source.SYNCED:
            # Lock sync turns an undated synced code on, not latchpoint, and the
            # clears a refused delete left are retried on their own (issue #221),
            # so this only gets here once nothing is left to clear (ADR 0082).
            raise DoorCodeInactive(
                "This synced door code is off and nothing is left to clear off its locks, so there's "
                "nothing to retry. If a delete was refused, delete it again to finish it."
            )
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
        # The withdraw below skips a code at the cap, and reads this copy first.
        code.push_attempt_count = 0
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

    # A synced code's added locks waiting to be brought in line go through their
    # reconcile, queued again now, or run here where the task doesn't (issue #220).
    # An off one's added locks its import lock confirmed it off for are taken off
    # here, like an inactive code's clears, without touching their flag, which is
    # what says the off was confirmed (issue #221).
    from locks.use_cases.added_lock_reconcile import rerequest_reconcile, run_reconciles_inline

    if code.is_active:
        reconcile_locks = rerequest_reconcile(door_code=code)
    else:
        reconcile_locks = off_clear_lock_entity_ids(door_code=code)

    if code.is_active and push_task_running():
        # Every failed lock was re-armed above, so the queued push gets them too.
        _request_push_best_effort(code=code, actor_user=actor_user)
        refresh_push_state(door_code=code)
        return fresh()

    if reconcile_locks:
        run_reconciles_inline(door_code=code, lock_entity_ids=reconcile_locks, zwavejs=zwavejs, actor_user=actor_user)

    push_or_settle_after_clear_retry(
        door_code=code,
        zwavejs=zwavejs,
        actor_user=actor_user,
        include_failed=True,
        lock_budget_seconds=PUSH_LOCK_BUDGET_SECONDS,
    )
    return fresh()
