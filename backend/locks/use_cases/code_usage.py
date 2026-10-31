"""Count door code uses from keypad unlocks on the lock (issue #145, ADR-0114).

A :class:`~locks.keypad_events.KeypadUnlock` says which node opened and from
which CC 99 slot. :func:`handle_keypad_unlock` maps that to the code assigned
to the slot and :func:`record_keypad_use` counts it. Uses are one total across
all of a code's locks. This only counts. It doesn't turn off a used up code or
wake anything, that's the next PR.

DB only, no Z-Wave I/O. The locks runtime runs it on its own worker thread
(``locks.runtime``), never on the ``zwavejs-events`` thread (ADR-0100).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone as django_timezone

from alarm.models import Entity
from locks.keypad_events import KeypadUnlock
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases.code_lifecycle import use_limit

logger = logging.getLogger(__name__)

# A second notification for the same lock and slot inside this window is the
# same unlock (a lock that reports it twice, or as both event 6 and 34).
DEDUPE_WINDOW = timedelta(seconds=10)

_SOURCE = "zwavejs"

# ``stale_reason`` on a use that wasn't counted because the slot may still hold
# an older PIN of the code, or the code is off and its PIN shouldn't be there.
_STALE_CLEAR_OUTSTANDING = "clear_outstanding"
_STALE_INACTIVE = "inactive"


class UseOutcome(StrEnum):
    COUNTED = "counted"
    DUPLICATE = "duplicate"
    STALE_SLOT = "stale_slot"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class _SlotMatch:
    door_code_id: int
    lock_entity_id: str


def lock_entity_ids_for_node(*, node_id: int) -> list[str]:
    """Entities linked to Z-Wave node ``node_id``, by ``attributes.zwavejs.node_id`` alone.

    The same rule the push uses to find a lock's node
    (``lock_config_sync._resolve_lock_node_id``), which doesn't look at the
    home id, so every lock that gets pushes gets counts.
    :func:`handle_keypad_unlock` warns when the lock's recorded home id isn't
    the connected one.
    """
    query = Entity.objects.filter(
        Q(attributes__zwavejs__node_id=node_id) | Q(attributes__zwavejs__node_id=str(node_id))
    )
    return list(query.order_by("entity_id").values_list("entity_id", flat=True))


def _warn_if_other_home(*, lock_entity_id: str, home_id: int | None, node_id: int) -> None:
    """Log a WARNING when ``lock_entity_id`` records a home id that isn't the connected network's.

    Entity sync records 0 when it didn't know the home id, so 0 or none is never a mismatch.
    """
    if not home_id or not lock_entity_id:
        return
    attrs = Entity.objects.filter(entity_id=lock_entity_id).values_list("attributes", flat=True).first()
    zwavejs = attrs.get("zwavejs") if isinstance(attrs, dict) else None
    recorded = zwavejs.get("home_id") if isinstance(zwavejs, dict) else None
    if recorded and recorded != home_id:
        logger.warning(
            "Door code use: %s records Z-Wave home id %s but the unlock came from home id %s (node %s). "
            "Counted anyway, the same as pushes resolve it",
            lock_entity_id,
            recorded,
            home_id,
            node_id,
        )


def _clear_outstanding_on(*, door_code: DoorCode, lock_entity_id: str, slot_index: int) -> bool:
    """Whether a clear of ``door_code``'s on this lock and slot hasn't gone through, so it may hold an older PIN."""
    from locks.use_cases.lock_push import unresolved_clear_failures

    return any(
        failure.lock_entity_id == lock_entity_id and failure.slot_index == slot_index
        for failure in unresolved_clear_failures(door_code=door_code)
    )


def _codes_with_clear_outstanding(*, lock_entity_ids: list[str], slot_index: int) -> list[_SlotMatch]:
    """Codes that no longer track this slot but whose clear of it hasn't gone through."""
    from locks.use_cases.lock_push import _CLEAR_FAILED_ACTION

    candidates = (
        DoorCodeEvent.objects.filter(
            lock_entity_id__in=lock_entity_ids,
            door_code__isnull=False,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata__action=_CLEAR_FAILED_ACTION,
        )
        .values_list("door_code_id", "lock_entity_id")
        .distinct()
    )
    matches: list[_SlotMatch] = []
    for door_code_id, lock_entity_id in sorted(set(candidates)):
        if _clear_outstanding_on(
            door_code=DoorCode(id=door_code_id), lock_entity_id=lock_entity_id, slot_index=slot_index
        ):
            matches.append(_SlotMatch(door_code_id=door_code_id, lock_entity_id=lock_entity_id))
    return matches


def _unmatched_lock(lock_entity_ids: list[str]) -> str:
    """The lock to put on a use no code matched, when the node's entities point at one."""
    if len(lock_entity_ids) == 1:
        return lock_entity_ids[0]
    locks = list(
        Entity.objects.filter(entity_id__in=lock_entity_ids, domain="lock").values_list("entity_id", flat=True)
    )
    if len(locks) == 1:
        return locks[0]
    with_codes = sorted(
        set(
            DoorCodeLockAssignment.objects.filter(lock_entity_id__in=lock_entity_ids).values_list(
                "lock_entity_id", flat=True
            )
        )
    )
    return with_codes[0] if len(with_codes) == 1 else ""


def _base_metadata(*, slot_index: int, notification_event: int) -> dict[str, object]:
    return {"slot_index": slot_index, "source": _SOURCE, "notification_event": notification_event}


def _is_duplicate(*, lock_entity_id: str, slot_index: int, now: datetime, node_id: int | None = None) -> bool:
    """Whether a use on this lock and slot was recorded within :data:`DEDUPE_WINDOW` of ``now``.

    ``now`` is when this use came in, and a use event's ``created_at`` is when
    it came in too (:func:`_create_use_event`), so a use that waited to be
    counted is compared by when it happened. A use with no lock goes by its
    node instead, so two unknown locks don't dedupe each other.
    """
    query = DoorCodeEvent.objects.filter(
        event_type=DoorCodeEvent.EventType.CODE_USED,
        lock_entity_id=lock_entity_id,
        metadata__slot_index=slot_index,
        created_at__gte=now - DEDUPE_WINDOW,
        created_at__lte=now + DEDUPE_WINDOW,
    )
    if not lock_entity_id:
        query = query.filter(metadata__node_id=node_id)
    return query.exists()


def _create_use_event(*, at: datetime, **fields) -> DoorCodeEvent:
    """A ``code_used`` event whose ``created_at`` is ``at``, when the use came in.

    ``created_at`` is ``auto_now_add``, so it's set after the insert.
    """
    event = DoorCodeEvent.objects.create(user=None, event_type=DoorCodeEvent.EventType.CODE_USED, **fields)
    DoorCodeEvent.objects.filter(id=event.id).update(created_at=at)
    event.created_at = at
    return event


def _record_unmatched(
    *, lock_entity_id: str, node_id: int | None, slot_index: int, notification_event: int, at: datetime
) -> None:
    metadata = {**_base_metadata(slot_index=slot_index, notification_event=notification_event), "unmatched": True}
    if node_id is not None:
        metadata["node_id"] = node_id
    _create_use_event(at=at, door_code=None, lock_entity_id=lock_entity_id, metadata=metadata)


def record_unmatched_use(
    *,
    lock_entity_id: str,
    node_id: int | None,
    slot_index: int,
    notification_event: int,
    now: datetime | None = None,
) -> UseOutcome:
    """A ``code_used`` event with no code for a slot nothing is assigned to, unless it's a duplicate."""
    now = now if now is not None else django_timezone.now()
    with transaction.atomic():
        if _is_duplicate(lock_entity_id=lock_entity_id, slot_index=slot_index, now=now, node_id=node_id):
            return UseOutcome.DUPLICATE
        _record_unmatched(
            lock_entity_id=lock_entity_id,
            node_id=node_id,
            slot_index=slot_index,
            notification_event=notification_event,
            at=now,
        )
    return UseOutcome.UNMATCHED


def record_keypad_use(
    *,
    door_code_id: int,
    lock_entity_id: str,
    slot_index: int,
    notification_event: int,
    node_id: int | None = None,
    now: datetime | None = None,
) -> UseOutcome:
    """Count one use of the code in ``slot_index`` on ``lock_entity_id``, in one transaction.

    Takes the code row first, like every writer of a code and its assignments,
    then checks the code still has this slot on this lock, or has a clear of it
    outstanding. When it has neither (the slot moved or the code is gone) the
    use is recorded with no code. A use on the same lock and slot inside
    :data:`DEDUPE_WINDOW` is a duplicate and records nothing. A slot that may
    still hold an older PIN (an unresolved clear) or a code that's off records a
    ``code_used`` event with ``stale_slot`` and isn't counted. Anything else adds
    one to ``uses_count`` with ``F()`` and sets ``last_used_at`` and
    ``last_used_lock``. ``over_limit`` in the event is whether this use went past
    the code's limit. Nothing is turned off here.
    """
    now = now if now is not None else django_timezone.now()
    base = _base_metadata(slot_index=slot_index, notification_event=notification_event)
    with transaction.atomic():
        code = DoorCode.objects.select_for_update().filter(id=door_code_id).first()
        holds_slot = (
            code is not None
            and DoorCodeLockAssignment.objects.filter(
                door_code_id=code.id, lock_entity_id=lock_entity_id, slot_index=slot_index
            ).exists()
        )
        clear_outstanding = code is not None and _clear_outstanding_on(
            door_code=code, lock_entity_id=lock_entity_id, slot_index=slot_index
        )
        if _is_duplicate(lock_entity_id=lock_entity_id, slot_index=slot_index, now=now):
            return UseOutcome.DUPLICATE
        if code is None or not (holds_slot or clear_outstanding):
            _record_unmatched(
                lock_entity_id=lock_entity_id,
                node_id=node_id,
                slot_index=slot_index,
                notification_event=notification_event,
                at=now,
            )
            return UseOutcome.UNMATCHED

        limit = use_limit(code)
        stale_reason = _STALE_CLEAR_OUTSTANDING if clear_outstanding else None
        if stale_reason is None and not code.is_active:
            stale_reason = _STALE_INACTIVE
        if stale_reason is not None:
            _create_use_event(
                at=now,
                door_code=code,
                lock_entity_id=lock_entity_id,
                metadata={
                    **base,
                    "uses_count": code.uses_count,
                    "max_uses": code.max_uses,
                    "over_limit": False,
                    "stale_slot": True,
                    "stale_reason": stale_reason,
                },
            )
            return UseOutcome.STALE_SLOT

        DoorCode.objects.filter(id=code.id).update(
            uses_count=F("uses_count") + 1, last_used_at=now, last_used_lock=lock_entity_id, updated_at=now
        )
        # The row is held, so this is the count the update just wrote.
        uses_count = code.uses_count + 1
        _create_use_event(
            at=now,
            door_code=code,
            lock_entity_id=lock_entity_id,
            metadata={
                **base,
                "uses_count": uses_count,
                "max_uses": code.max_uses,
                "over_limit": limit is not None and uses_count > limit,
            },
        )
    return UseOutcome.COUNTED


def handle_keypad_unlock(unlock: KeypadUnlock, *, home_id: int | None, now: datetime | None = None) -> UseOutcome:
    """Map a keypad unlock to the code in its slot and record it (:func:`record_keypad_use`).

    The node's entities give the locks (:func:`lock_entity_ids_for_node`), and
    the slot gives the assignment. No assignment falls back to a code with a
    clear of that slot outstanding, which is recorded as ``stale_slot``.
    Nothing at all is a ``code_used`` event with no code. More than one match
    (two lock entities for the node with a code in the same slot) is logged and
    skipped, since there's no telling which code it was. A lock whose recorded
    home id isn't ``home_id`` is still counted, with a WARNING.

    The use is dated ``now``, else when the listener got it
    (``unlock.received_at``), else when this runs.
    """
    if now is None:
        now = unlock.received_at if unlock.received_at is not None else django_timezone.now()
    lock_entity_ids = lock_entity_ids_for_node(node_id=unlock.node_id)
    if not lock_entity_ids:
        logger.info(
            "Door code use: no entity for Z-Wave node %s (slot %s), nothing recorded", unlock.node_id, unlock.slot
        )
        return UseOutcome.UNMATCHED

    matches = [
        _SlotMatch(door_code_id=door_code_id, lock_entity_id=lock_entity_id)
        for door_code_id, lock_entity_id in DoorCodeLockAssignment.objects.filter(
            lock_entity_id__in=lock_entity_ids, slot_index=unlock.slot
        )
        .order_by("id")
        .values_list("door_code_id", "lock_entity_id")
    ]
    if not matches:
        matches = _codes_with_clear_outstanding(lock_entity_ids=lock_entity_ids, slot_index=unlock.slot)

    if len(matches) > 1:
        logger.warning(
            "Door code use: node %s slot %s matches %d codes (%s), skipped",
            unlock.node_id,
            unlock.slot,
            len(matches),
            ", ".join(f"code {m.door_code_id} on {m.lock_entity_id}" for m in matches),
        )
        return UseOutcome.AMBIGUOUS

    if not matches:
        lock_entity_id = _unmatched_lock(lock_entity_ids)
        _warn_if_other_home(lock_entity_id=lock_entity_id, home_id=home_id, node_id=unlock.node_id)
        outcome = record_unmatched_use(
            lock_entity_id=lock_entity_id,
            node_id=unlock.node_id,
            slot_index=unlock.slot,
            notification_event=unlock.event,
            now=now,
        )
        logger.info(
            "Door code use: %s on %s (node %s) slot %s, no code has that slot",
            outcome,
            lock_entity_id or "an unknown lock",
            unlock.node_id,
            unlock.slot,
        )
        return outcome

    match = matches[0]
    _warn_if_other_home(lock_entity_id=match.lock_entity_id, home_id=home_id, node_id=unlock.node_id)
    outcome = record_keypad_use(
        door_code_id=match.door_code_id,
        lock_entity_id=match.lock_entity_id,
        slot_index=unlock.slot,
        notification_event=unlock.event,
        node_id=unlock.node_id,
        now=now,
    )
    logger.info(
        "Door code use: %s for code %s on %s (node %s) slot %s, event %s",
        outcome,
        match.door_code_id,
        match.lock_entity_id,
        unlock.node_id,
        unlock.slot,
        unlock.event,
    )
    return outcome
