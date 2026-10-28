"""Programs door-code PINs and CC 78 schedules onto physical Z-Wave JS locks (ADR 0092).

The companion to ``lock_config_sync.sync_lock_config`` (pull-sync). Whereas
pull-sync reads the lock and reconciles into the DB, ``push_door_code_to_lock``
takes a saved ``DoorCode`` row, picks the lowest free slot on the target lock,
sends CC 99 ``set`` (user code), reads the slot back with CC 99 ``get`` to confirm
the lock stored it, then an optional CC 78 ``setDailyRepeatingSchedule`` per
weekday, and records the slot assignment + push state.

The use case is intended to be called synchronously from the create/update API
paths. It commits as much progress as it makes; transient failures land the row
at ``push_state="pending"`` for the scheduler to retry.
"""

from __future__ import annotations

import logging
import re
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.utils import timezone as django_timezone
from integrations_zwavejs.manager import (
    ZwavejsClientUnavailable,
    ZwavejsCommandValidationError,
    ZwavejsNotConfigured,
)

from alarm.crypto import InvalidToken, SettingsEncryption
from config.domain_exceptions import ConflictError, GatewayError, ValidationError
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases.lock_config_sync import (
    CC_SCHEDULE_ENTRY_LOCK,
    CC_USER_CODE,
    _coerce_int,
    _normalize_pin,
    _parse_user_code_status,
    _release_sync_lock,
    _resolve_lock_node_id,
    _try_acquire_sync_lock,
    clear_lock_user_code_slot,
)
from locks.use_cases.lock_config_sync import (
    InvalidRequest as LockSyncInvalidRequest,
)
from locks.use_cases.lock_config_sync import (
    NotFound as LockSyncNotFound,
)

if TYPE_CHECKING:
    from alarm.gateways.zwavejs import ZwavejsGateway

logger = logging.getLogger(__name__)

# Weekday bit -> CC 78 ScheduleEntryLockWeekday (Sunday=0, Monday=1 .. Saturday=6).
# Mirrors the read path's _weekday_to_mask_index inversion. NOTE: Sunday is 0, not 7
# — node-zwave-js's ScheduleEntryLockWeekday enum has no value 7.
_WEEKDAY_BIT_TO_ZWAVE = {
    0: 1,  # Monday
    1: 2,
    2: 3,
    3: 4,
    4: 5,
    5: 6,  # Saturday
    6: 0,  # Sunday
}


class InvalidPin(ValidationError):
    """The DoorCode does not carry a usable plaintext PIN (missing/length/format)."""


class LockSlotsFull(ConflictError):
    """The target lock has no Available user-code slots."""


class LockUnreachable(ConflictError):
    """The lock is currently not reachable; safe to retry later."""


class LockPushFailed(GatewayError):
    """The lock returned a terminal error or push retries are exhausted."""

    gateway_name = "zwavejs"


class LockRejectedCode(LockPushFailed):
    """The lock will not or did not store the PIN (admin-code clash, or the slot reads back without it).

    ``clear_slot`` is set when the slot we just wrote might still hold the PIN
    (read back holding it disabled, or read back empty but possibly committed
    late), so the push path clears it rather than leave a PIN on the lock nothing
    tracks. ``holds_pin`` is set only when the readback showed the PIN itself.
    """

    def __init__(self, message: str, *, clear_slot: bool = False, holds_pin: bool = False):
        super().__init__(message)
        self.clear_slot = clear_slot
        self.holds_pin = holds_pin


class LockCodeUnverified(GatewayError):
    """The slot could not be read back after the ``set``; transient, the scheduler retries."""

    gateway_name = "zwavejs"


@dataclass
class PushResult:
    lock_entity_id: str
    node_id: int
    slot_index: int
    schedule_applied: bool = False
    weekdays_pushed: list[int] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _decrypt_pin_or_raise(door_code: DoorCode) -> str:
    """Return the plaintext PIN. Raises :class:`InvalidPin` if missing/unreadable."""
    if not door_code.encrypted_pin:
        raise InvalidPin("Door code has no stored PIN to push.")
    try:
        plaintext = SettingsEncryption.get().decrypt(door_code.encrypted_pin)
    except (ValueError, InvalidToken) as exc:
        raise InvalidPin("Stored PIN could not be decrypted.") from exc
    text = (plaintext or "").strip()
    if not text.isdigit():
        raise InvalidPin("Stored PIN is not numeric.")
    if len(text) < 4 or len(text) > 8:
        raise InvalidPin("Stored PIN must be 4 to 8 digits.")
    return text


def _enumerate_free_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    timeout_seconds: float,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> int:
    """Return the lowest free user-code slot on the node. Raises :class:`LockSlotsFull`.

    ``claimed_slots`` are slots the DB already has a ``DoorCodeLockAssignment`` for
    on this lock. They are skipped even when the Z-Wave JS value cache still reads
    them as Available, which it does for a while after a CC 99 ``set``.
    """
    value_ids = zwavejs.node_get_defined_value_ids(node_id=node_id, timeout_seconds=timeout_seconds)
    if not isinstance(value_ids, list):
        value_ids = []

    cc99 = [vid for vid in value_ids if isinstance(vid, dict) and vid.get("commandClass") == CC_USER_CODE]
    if not cc99:
        raise LockPushFailed("Lock does not expose User Code (CC 99) value IDs.")

    users_number_vid = next(
        (vid for vid in cc99 if isinstance(vid.get("property"), str) and vid.get("property") == "usersNumber"),
        None,
    )
    max_slots: int | None = None
    if users_number_vid is not None:
        try:
            raw = zwavejs.node_get_value(node_id=node_id, value_id=users_number_vid, timeout_seconds=timeout_seconds)
            if isinstance(raw, int) and raw > 0:
                max_slots = int(raw)
        except Exception:
            max_slots = None
    if max_slots is None:
        keys: set[int] = set()
        for vid in cc99:
            if vid.get("property") not in {"userIdStatus", "userCode"}:
                continue
            key = vid.get("propertyKey")
            if isinstance(key, int) and key >= 0:
                keys.add(int(key))
        if keys:
            max_slots = max(keys)

    if not isinstance(max_slots, int) or max_slots <= 0:
        raise LockPushFailed("Unable to determine lock user-code slot count.")

    for slot_index in range(1, int(max_slots) + 1):
        if slot_index in claimed_slots:
            continue
        status_vid = {
            "commandClass": CC_USER_CODE,
            "property": "userIdStatus",
            "propertyKey": slot_index,
        }
        try:
            status_value = zwavejs.node_get_value(node_id=node_id, value_id=status_vid, timeout_seconds=timeout_seconds)
        except Exception:
            # Treat unknown status as occupied to avoid clobbering a real code.
            continue
        is_occupied, _is_active = _parse_user_code_status(status_value)
        if not is_occupied:
            return slot_index

    raise LockSlotsFull("All user-code slots on this lock are occupied.")


def _refresh_user_code_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    timeout_seconds: float,
) -> object:
    """Send CC 99 ``get`` for one slot so Z-Wave JS re-reads it from the lock.

    Returns whatever the CC API call returns (the slot's status/code report).
    Gateway errors propagate; callers decide whether a failed refresh matters.
    """
    return zwavejs.invoke_cc_api(
        node_id=node_id,
        command_class=CC_USER_CODE,
        method_name="get",
        args=[slot_index],
        timeout_seconds=timeout_seconds,
    )


def _raise_if_pin_matches_admin_code(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    pin: str,
    timeout_seconds: float,
) -> None:
    """Raise :class:`LockRejectedCode` when ``pin`` equals the lock's CC 99 ``adminCode``.

    Yale locks silently drop a user code that matches the admin code while the
    ``set`` call still returns normally (issue #107). Only checked when the lock
    exposes a readable ``adminCode`` value; any read problem skips the check and
    leaves it to the post-set readback.
    """
    try:
        value_ids = zwavejs.node_get_defined_value_ids(node_id=node_id, timeout_seconds=timeout_seconds)
        admin_vid = next(
            (
                vid
                for vid in (value_ids if isinstance(value_ids, list) else [])
                if isinstance(vid, dict)
                and vid.get("commandClass") == CC_USER_CODE
                and vid.get("property") == "adminCode"
            ),
            None,
        )
        if admin_vid is None:
            return
        raw = zwavejs.node_get_value(node_id=node_id, value_id=admin_vid, timeout_seconds=timeout_seconds)
    except Exception:
        logger.debug("Could not read adminCode for node %d; skipping admin-code check", node_id, exc_info=True)
        return

    known, admin_code = _normalize_pin(raw)
    if known and admin_code == pin:
        raise LockRejectedCode("PIN matches this lock's admin code. Choose a different PIN.")


# Delays between CC 99 ``get`` readback attempts after a ``set``. Battery locks
# can be slow to answer right after a write, so one timeout is not a verdict.
_READBACK_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0)

# CC 99 userIdStatus "Available": the slot is definitively empty.
_USER_ID_STATUS_AVAILABLE = 0


def _verify_user_code_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    pin: str,
    timeout_seconds: float,
) -> bool:
    """Read ``slot_index`` back with CC 99 ``get`` and confirm it holds ``pin``.

    Returns ``True`` when the lock reported ``pin`` itself and ``False`` when the
    slot reads back occupied with a masked/unreadable code, which is accepted
    (with a warning) since that's all such a lock lets us confirm.

    Raises :class:`LockRejectedCode` (terminal) when the lock answers and the slot
    holds a different code or holds the code disabled, or answers empty twice
    (one empty answer is asked again, since a lock still committing the write can
    report Available right after the set). Raises :class:`LockCodeUnverified`
    (transient) when no attempt gets a usable answer, including a single empty
    answer followed only by silence. Terminal config errors propagate unchanged.
    """
    attempts = len(_READBACK_RETRY_DELAYS_SECONDS) + 1
    last_reason = "no response"
    empty_answers = 0
    for attempt in range(attempts):
        if attempt:
            _time.sleep(_READBACK_RETRY_DELAYS_SECONDS[attempt - 1])
        try:
            response = _refresh_user_code_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                timeout_seconds=timeout_seconds,
            )
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable):
            raise
        except GatewayError as exc:
            last_reason = f"{exc.__class__.__name__}: {exc}"
            continue

        if isinstance(response, dict) and "response" in response:
            response = response["response"]
        if not isinstance(response, dict):
            last_reason = "lock returned no user code report"
            continue

        status = response.get("userIdStatus")
        if _coerce_int(status) == _USER_ID_STATUS_AVAILABLE:
            empty_answers += 1
            if empty_answers >= 2:
                raise LockRejectedCode(
                    f"Lock did not store the code: slot {slot_index} reads back empty.",
                    clear_slot=True,
                )
            last_reason = "slot read back empty once"
            continue
        occupied, is_active = _parse_user_code_status(status)
        if not occupied:
            # e.g. 254 "status not available" — not a verdict, ask again.
            last_reason = f"unknown userIdStatus {status!r}"
            continue
        known, stored = _normalize_pin(response.get("userCode"))
        if is_active is False:
            # We always send userIdStatus=1 (enabled); a disabled code won't open the door.
            # Only our own PIN gets cleared: a disabled slot with any other or an
            # unreadable code may be someone else's (our set may have been dropped).
            if known and stored == pin:
                raise LockRejectedCode(
                    f"Lock stored the code in slot {slot_index} but reports it disabled.",
                    clear_slot=True,
                    holds_pin=True,
                )
            if known:
                raise LockRejectedCode(f"Lock did not store the code: slot {slot_index} holds a different code.")
            raise LockRejectedCode(f"Lock reports slot {slot_index} disabled and its code can't be read back.")

        if not known:
            logger.warning(
                "Slot %d on node %d reads back occupied but userCode is %s; accepting without comparing",
                slot_index,
                node_id,
                "masked or unreadable" if "userCode" in response else "missing from the report",
            )
            return False
        if stored != pin:
            raise LockRejectedCode(f"Lock did not store the code: slot {slot_index} holds a different code.")
        return True

    raise LockCodeUnverified(f"Could not read back slot {slot_index} after {attempts} attempts ({last_reason}).")


# DoorCodeEvent metadata ``action`` for a push that sent the PIN to a slot but
# didn't get it confirmed. The slot is what a later retry may adopt.
_UNCONFIRMED_PUSH_ACTION = "push_unconfirmed"


def _record_unconfirmed_slot_attempt(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    slot_index: int,
    reason: str,
) -> None:
    """Remember that ``slot_index`` on this lock may hold this code's PIN (no schema change)."""
    DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": _UNCONFIRMED_PUSH_ACTION,
            "slot_index": int(slot_index),
            "reason": sanitize_push_error_for_storage(reason)[:200],
        },
    )


def _claimed_slots(*, lock_entity_id: str, door_code: DoorCode) -> set[int]:
    """Slots other door codes' assignments hold on this lock (skipped by selection, adoption and cleanup)."""
    return set(
        DoorCodeLockAssignment.objects.filter(lock_entity_id=lock_entity_id, slot_index__isnull=False)
        .exclude(door_code=door_code)
        .values_list("slot_index", flat=True)
    )


def _unconfirmed_attempt_slots(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> list[int]:
    """Slots recorded by :func:`_record_unconfirmed_slot_attempt` for this code on this lock.

    Only attempts since the code's last successful push to this lock count, newest
    first, without duplicates or ``claimed_slots``.
    """
    events = DoorCodeEvent.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id)
    last_pushed_id = (
        events.filter(event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
    )
    attempts = events.filter(event_type=DoorCodeEvent.EventType.CODE_FAILED)
    if last_pushed_id is not None:
        attempts = attempts.filter(id__gt=last_pushed_id)

    slots: list[int] = []
    for metadata in attempts.order_by("-id").values_list("metadata", flat=True):
        if not isinstance(metadata, dict) or metadata.get("action") != _UNCONFIRMED_PUSH_ACTION:
            continue
        slot_index = _coerce_int(metadata.get("slot_index"))
        if slot_index is None or slot_index <= 0 or slot_index in slots or slot_index in claimed_slots:
            continue
        slots.append(slot_index)
    return slots


def _find_adoptable_attempted_slot(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    door_code: DoorCode,
    lock_entity_id: str,
    pin: str,
    timeout_seconds: float,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> int | None:
    """Return a slot an earlier unconfirmed push of this code wrote on this lock, if it holds the PIN.

    Covers a code that landed while every readback timed out: the slot wasn't
    claimed, so a retry would otherwise write the PIN to a new slot, the lock
    would drop it as a duplicate, and the first slot would keep working with
    nothing tracking it. Only slots recorded by
    :func:`_record_unconfirmed_slot_attempt` for this same code and lock since
    its last successful push there are considered, never an arbitrary slot that
    happens to hold the same PIN (e.g. one entered on the keypad). ``claimed_slots``
    (the DB-held set ``_enumerate_free_slot`` skips) are never adopted, and the
    readback must report the PIN itself; a masked readback doesn't count.
    :class:`LockCodeUnverified` propagates.
    """
    candidates = _unconfirmed_attempt_slots(
        door_code=door_code,
        lock_entity_id=lock_entity_id,
        claimed_slots=claimed_slots,
    )
    for slot_index in candidates:
        try:
            confirmed = _verify_user_code_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                pin=pin,
                timeout_seconds=timeout_seconds,
            )
        except LockRejectedCode:
            continue
        if confirmed:
            return slot_index
    return None


def decrypt_pin_or_none(door_code: DoorCode) -> str | None:
    """Return the stored plaintext PIN, or ``None`` when it's missing or unreadable."""
    try:
        return _decrypt_pin_or_raise(door_code)
    except InvalidPin:
        return None


def has_unconfirmed_attempt_slots(*, door_code: DoorCode) -> bool:
    """Whether any of ``door_code``'s locks has a recorded unconfirmed slot that may hold its PIN."""
    for lock_entity_id in DoorCodeLockAssignment.objects.filter(door_code=door_code).values_list(
        "lock_entity_id", flat=True
    ):
        claimed = _claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code)
        if _unconfirmed_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id, claimed_slots=claimed):
            return True
    return False


# DoorCodeEvent metadata ``action`` for a CC 99 clear that failed transiently, so
# the slot may still hold the PIN (issue #139). A later ``code_removed`` event with
# ``_CLEAR_RESOLVED_ACTION`` for the same lock and slot settles it. No schema change.
_CLEAR_FAILED_ACTION = "clear_failed"
_CLEAR_RESOLVED_ACTION = "clear_resolved"


@dataclass(frozen=True)
class ClearFailure:
    """A slot on a lock that a clear didn't reach, so it may still hold the code's PIN.

    ``removing`` is set when the lock was being dropped from the code (its
    assignment is kept until the clear works). ``unconfirmed`` is set for a slot
    only known from a ``push_unconfirmed`` attempt, which is read back before
    it's cleared. ``permanent`` failures (the lock entity is gone or has no Z-Wave
    node) can't be retried and aren't recorded as events.
    """

    lock_entity_id: str
    slot_index: int
    reason: str
    removing: bool = False
    unconfirmed: bool = False
    permanent: bool = False

    def as_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "lock_entity_id": self.lock_entity_id,
            "slot_index": self.slot_index,
            "reason": self.reason,
        }
        if self.permanent:
            metadata["permanent"] = True
        return metadata


def is_permanent_clear_error(exc: Exception) -> bool:
    """A clear error that retrying can't fix: latchpoint can't resolve the lock to a Z-Wave node."""
    return isinstance(exc, (LockSyncNotFound, LockSyncInvalidRequest))


def _clear_error_reason(exc: Exception) -> str:
    return sanitize_push_error_for_storage(f"{exc.__class__.__name__}: {exc}")[:200]


def unresolved_clear_failures(*, door_code: DoorCode) -> list[ClearFailure]:
    """Clear failures recorded for ``door_code`` that no later clear has settled, oldest first."""
    pending: dict[tuple[str, int], ClearFailure] = {}
    events = (
        DoorCodeEvent.objects.filter(
            door_code=door_code, metadata__action__in=[_CLEAR_FAILED_ACTION, _CLEAR_RESOLVED_ACTION]
        )
        .order_by("id")
        .values_list("lock_entity_id", "metadata")
    )
    for lock_entity_id, metadata in events:
        slot_index = _coerce_int(metadata.get("slot_index")) if isinstance(metadata, dict) else None
        if not slot_index or slot_index <= 0:
            continue
        key = (lock_entity_id, slot_index)
        if metadata.get("action") == _CLEAR_FAILED_ACTION:
            pending[key] = ClearFailure(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                reason=str(metadata.get("reason") or ""),
                removing=bool(metadata.get("removing")),
                unconfirmed=bool(metadata.get("unconfirmed")),
            )
        else:
            pending.pop(key, None)
    return list(pending.values())


def describe_clear_failure(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int, exc: Exception
) -> ClearFailure:
    """Log a failed clear and describe it, without recording anything."""
    logger.warning(
        "Could not clear slot %d on %s for door code id=%s; it may still hold the PIN",
        slot_index,
        lock_entity_id,
        door_code.id,
        exc_info=True,
    )
    return ClearFailure(
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
        reason=_clear_error_reason(exc),
        permanent=is_permanent_clear_error(exc),
    )


def record_clear_failure(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    slot_index: int,
    exc: Exception,
    removing: bool = False,
    unconfirmed: bool = False,
) -> ClearFailure:
    """Log a failed clear and, unless it's permanent, record it on the lock so it gets retried.

    One event per slot until it's settled; a repeat failure only adds an event
    when it changes the flags (a tracked slot that's now being dropped, say).
    """
    described = describe_clear_failure(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, exc=exc
    )
    if described.permanent:
        return described
    reason = described.reason

    current = next(
        (
            f
            for f in unresolved_clear_failures(door_code=door_code)
            if (f.lock_entity_id, f.slot_index) == (lock_entity_id, slot_index)
        ),
        None,
    )
    if current is not None:
        removing = removing or current.removing
        unconfirmed = unconfirmed and current.unconfirmed
    failure = ClearFailure(
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
        reason=reason,
        removing=removing,
        unconfirmed=unconfirmed,
    )
    if current is None or (current.removing, current.unconfirmed) != (removing, unconfirmed):
        DoorCodeEvent.objects.create(
            door_code=door_code,
            user=door_code.user,
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={
                "action": _CLEAR_FAILED_ACTION,
                "slot_index": int(slot_index),
                "reason": reason,
                **({"removing": True} if removing else {}),
                **({"unconfirmed": True} if unconfirmed else {}),
            },
        )
    return failure


def resolve_clear_failure(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int, outcome: str
) -> ClearFailure | None:
    """Settle a recorded clear failure for this slot (if any) and return it."""
    current = next(
        (
            f
            for f in unresolved_clear_failures(door_code=door_code)
            if (f.lock_entity_id, f.slot_index) == (lock_entity_id, slot_index)
        ),
        None,
    )
    if current is not None:
        DoorCodeEvent.objects.create(
            door_code=door_code,
            user=door_code.user,
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_REMOVED,
            metadata={"action": _CLEAR_RESOLVED_ACTION, "slot_index": int(slot_index), "outcome": outcome},
        )
    return current


def forget_cleared_slot(*, door_code: DoorCode, lock_entity_id: str, slot_index: int, outcome: str) -> bool:
    """Call once ``slot_index`` on the lock no longer holds the PIN (or can't be reached at all).

    Settles any recorded failure for it and stops tracking the slot. An
    assignment whose lock was being dropped is deleted; any other just loses its
    ``slot_index`` so the code gets pushed there again. Returns ``True`` when the
    assignment was deleted.
    """
    failure = resolve_clear_failure(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome=outcome
    )
    assignment = DoorCodeLockAssignment.objects.filter(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
    )
    if failure is not None and failure.removing:
        assignment.delete()
        return True
    assignment.update(slot_index=None)
    return False


def clear_failures_message(failures: list[ClearFailure]) -> str:
    return "; ".join(
        f"Couldn't clear slot {f.slot_index} on {f.lock_entity_id}, it may still hold the PIN ({f.reason})"
        for f in failures
    )


def settle_clear_failure_state(*, door_code: DoorCode) -> bool:
    """Keep a code with unresolved clear failures from showing ``pushed``. Returns whether it has any.

    The code goes ``pending`` so the scheduler retries the clears (a terminal
    ``failed`` stays), and ``last_push_error`` leads with the slots that may
    still hold the PIN, keeping any other error after them.
    """
    failures = unresolved_clear_failures(door_code=door_code)
    if not failures:
        return False
    door_code.refresh_from_db(fields=["push_state", "last_push_error"])
    other_errors = [
        part
        for part in (door_code.last_push_error or "").split("; ")
        if part and not part.startswith("Couldn't clear slot")
    ]
    state = door_code.push_state if door_code.push_state == DoorCode.PushState.FAILED else DoorCode.PushState.PENDING
    error = sanitize_push_error_for_storage("; ".join([clear_failures_message(failures), *other_errors]))[:500]
    if (door_code.push_state, door_code.last_push_error) != (state, error):
        door_code.push_state = state
        door_code.last_push_error = error
        door_code.save(update_fields=["push_state", "last_push_error", "updated_at"])
    return True


def mark_pushed_if_settled(*, door_code: DoorCode) -> bool:
    """Mark an active code ``pushed`` when every lock holds a slot and no clear is outstanding.

    Nothing else recomputes ``push_state`` when no lock needed pushing, so a
    failure left by a dropped lock or a since-fixed clear would otherwise stick.
    """
    assignments = DoorCodeLockAssignment.objects.filter(door_code=door_code)
    if (
        not assignments.exists()
        or assignments.filter(slot_index__isnull=True).exists()
        or unresolved_clear_failures(door_code=door_code)
    ):
        return False
    door_code.refresh_from_db(fields=["push_state", "last_push_error", "push_attempt_count"])
    if door_code.push_state != DoorCode.PushState.PUSHED or door_code.last_push_error:
        door_code.push_state = DoorCode.PushState.PUSHED
        door_code.last_push_error = ""
        door_code.push_attempt_count = 0
        door_code.save(update_fields=["push_state", "last_push_error", "push_attempt_count", "updated_at"])
    return True


def retry_failed_slot_clears(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> list[ClearFailure]:
    """Retry the clears recorded by :func:`record_clear_failure`. Returns the ones still failing.

    A cleared slot is forgotten (:func:`forget_cleared_slot`), so a kept lock gets
    pushed again and a dropped lock's assignment goes. An unconfirmed slot is
    only cleared when it reads back holding the code's current PIN, and is
    settled without a clear once an assignment tracks it. A lock that can't be
    resolved any more is settled as ``lock_missing``. A failure still failing
    bumps ``push_attempt_count`` so the scheduler's attempt cap applies.
    """
    still_failing: list[ClearFailure] = []
    for failure in unresolved_clear_failures(door_code=door_code):
        lock_entity_id, slot_index = failure.lock_entity_id, failure.slot_index
        try:
            if failure.unconfirmed:
                if DoorCodeLockAssignment.objects.filter(lock_entity_id=lock_entity_id, slot_index=slot_index).exists():
                    resolve_clear_failure(
                        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="tracked"
                    )
                    continue
                pin = decrypt_pin_or_none(door_code)
                holds_pin = False
                if pin:
                    try:
                        holds_pin = _verify_user_code_slot(
                            zwavejs=zwavejs,
                            node_id=_resolve_lock_node_id(lock_entity_id=lock_entity_id),
                            slot_index=slot_index,
                            pin=pin,
                            timeout_seconds=timeout_seconds,
                        )
                    except LockRejectedCode as exc:
                        holds_pin = exc.holds_pin
                if not holds_pin:
                    resolve_clear_failure(
                        door_code=door_code,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                        outcome="not_holding_pin",
                    )
                    continue
            clear_lock_user_code_slot(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                zwavejs=zwavejs,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            if is_permanent_clear_error(exc):
                logger.warning("Can't resolve %s to clear slot %d; no longer tracking it", lock_entity_id, slot_index)
                forget_cleared_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
                continue
            logger.warning(
                "Retrying the clear of slot %d on %s for door code id=%s failed again",
                slot_index,
                lock_entity_id,
                door_code.id,
                exc_info=True,
            )
            still_failing.append(
                ClearFailure(
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason=_clear_error_reason(exc),
                    removing=failure.removing,
                    unconfirmed=failure.unconfirmed,
                )
            )
            continue
        forget_cleared_slot(
            door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
        )

    if still_failing:
        door_code.refresh_from_db(fields=["push_attempt_count"])
        door_code.push_attempt_count = (door_code.push_attempt_count or 0) + 1
        door_code.last_push_attempt_at = django_timezone.now()
        door_code.save(update_fields=["push_attempt_count", "last_push_attempt_at", "updated_at"])
    return still_failing


def clear_unconfirmed_slots_holding_pin(
    *,
    door_code: DoorCode,
    pin: str,
    lock_entity_ids: list[str],
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> tuple[list[dict[str, object]], list[ClearFailure]]:
    """Clear slots an unconfirmed push of ``door_code`` may have left ``pin`` in.

    For deleting, deactivating or changing the PIN of a code that is still
    pending: its PIN may have landed in a slot latchpoint never recorded
    (``slot_index`` stays empty until the readback confirms), so the usual
    "clear assigned slots" pass misses it. Candidates are the same recorded
    attempts adoption uses. A slot is cleared only when it reads back holding
    ``pin`` (enabled or disabled); empty, masked or different codes are left
    alone. A slot that can't be checked or cleared is recorded with
    :func:`record_clear_failure` (``unconfirmed``) so it's retried. Returns the
    slots cleared as ``{"lock_entity_id", "slot_index"}`` dicts and the
    failures. Doesn't take the ``lock_sync:`` lock, same as the existing slot
    clears in those paths.
    """
    cleared: list[dict[str, object]] = []
    failed: list[ClearFailure] = []
    for lock_entity_id in dict.fromkeys(lock_entity_ids):
        slots = _unconfirmed_attempt_slots(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            claimed_slots=_claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code),
        )
        if not slots:
            continue
        try:
            node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
        except Exception:
            logger.warning("Can't resolve %s to check unconfirmed door code slots %s", lock_entity_id, slots)
            continue
        for slot_index in slots:
            try:
                try:
                    holds_pin = _verify_user_code_slot(
                        zwavejs=zwavejs,
                        node_id=node_id,
                        slot_index=slot_index,
                        pin=pin,
                        timeout_seconds=timeout_seconds,
                    )
                except LockRejectedCode as exc:
                    holds_pin = exc.holds_pin
                if not holds_pin:
                    resolve_clear_failure(
                        door_code=door_code,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                        outcome="not_holding_pin",
                    )
                    continue
                clear_lock_user_code_slot(
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    zwavejs=zwavejs,
                    timeout_seconds=timeout_seconds,
                )
                cleared.append({"lock_entity_id": lock_entity_id, "slot_index": slot_index})
                resolve_clear_failure(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
                )
            except Exception as exc:
                logger.warning(
                    "Could not check/clear unconfirmed slot %d on %s for door code id=%s; it may still hold the PIN",
                    slot_index,
                    lock_entity_id,
                    door_code.id,
                )
                failed.append(
                    record_clear_failure(
                        door_code=door_code,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                        exc=exc,
                        unconfirmed=True,
                    )
                )
    return cleared, failed


def _clear_slot_best_effort(
    *,
    zwavejs: ZwavejsGateway,
    lock_entity_id: str,
    slot_index: int,
    timeout_seconds: float,
) -> None:
    """Clear a slot we just wrote whose readback rejected the code; failures are only logged.

    Safe because the slot was free when this push picked it.
    """
    try:
        clear_lock_user_code_slot(
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            zwavejs=zwavejs,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        logger.warning(
            "Could not clear slot %d on %s after the lock rejected the code; it may still hold the PIN",
            slot_index,
            lock_entity_id,
            exc_info=True,
        )


# CC 78 daily-repeating schedules are time-based, so "all day" is the widest
# expressible window: 00:00 for 23h59m. Used when a code restricts days but
# carries no explicit time-of-day window.
_FULL_DAY_START = time(0, 0)
_FULL_DAY_DURATION = (23, 59)


def _compute_schedule_duration(window_start: time, window_end: time) -> tuple[int, int]:
    """Return (durationHour, durationMinute) for a same-day window."""
    start_dt = datetime(2000, 1, 1, window_start.hour, window_start.minute, tzinfo=timezone.utc)
    end_dt = datetime(2000, 1, 1, window_end.hour, window_end.minute, tzinfo=timezone.utc)
    if end_dt <= start_dt:
        raise InvalidPin("Schedule window_end must be after window_start (same-day).")
    delta: timedelta = end_dt - start_dt
    total_minutes = int(delta.total_seconds() // 60)
    return total_minutes // 60, total_minutes % 60


def _push_daily_repeating_schedule(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    door_code: DoorCode,
    timeout_seconds: float,
) -> list[int]:
    """Push CC 78 daily-repeating schedule for each enabled weekday. Returns ZW weekday ints used.

    When the code restricts days but carries no time-of-day window, the schedule
    falls back to a full-day window (00:00 + 23h59m) so the day restriction still
    reaches the lock. The stored model is not mutated — synthesis happens here only.
    """
    if door_code.days_of_week is None:
        return []

    if door_code.window_start and door_code.window_end:
        start = door_code.window_start
        duration_h, duration_m = _compute_schedule_duration(start, door_code.window_end)
    else:
        start = _FULL_DAY_START
        duration_h, duration_m = _FULL_DAY_DURATION
    if duration_h == 0 and duration_m == 0:
        return []

    weekdays_pushed: list[int] = []
    for bit, zwave_weekday in _WEEKDAY_BIT_TO_ZWAVE.items():
        if not (int(door_code.days_of_week) & (1 << bit)):
            continue
        slot_id = bit + 1
        # setDailyRepeatingSchedule(slot, schedule) — two positional args.
        slot = {"userId": slot_index, "slotId": slot_id}
        schedule = {
            "weekdays": [zwave_weekday],
            "startHour": start.hour,
            "startMinute": start.minute,
            "durationHour": duration_h,
            "durationMinute": duration_m,
        }
        zwavejs.invoke_cc_api(
            node_id=node_id,
            command_class=CC_SCHEDULE_ENTRY_LOCK,
            method_name="setDailyRepeatingSchedule",
            args=[slot, schedule],
            timeout_seconds=timeout_seconds,
        )
        weekdays_pushed.append(zwave_weekday)
    return weekdays_pushed


# Mask any run of 4–8 consecutive digits in stored error strings. PINs in this
# system are 4–8 digits; slot indices (1–99) and node IDs (1–232) are 1–3 digits;
# HTTP status codes are 3 digits; ZJS home_ids are 10+ digits — so this band
# masks accidental PIN leaks without scrubbing useful diagnostic numbers.
_PIN_LIKE_DIGIT_RUN = re.compile(r"(?<!\d)\d{4,8}(?!\d)")


def sanitize_push_error_for_storage(message: str | None) -> str:
    """Return ``message`` with any 4–8-digit run replaced by ``****``.

    Defense-in-depth against a future gateway / exception class that includes
    user-supplied data in its ``__str__``: keeps PIN material out of
    ``DoorCode.last_push_error`` and ``DoorCodeEvent.metadata`` even if upstream
    error messages start carrying it.
    """
    if not message:
        return ""
    return _PIN_LIKE_DIGIT_RUN.sub("****", str(message))


def _record_push_failure(
    *,
    door_code: DoorCode,
    error_message: str,
    terminal: bool,
) -> None:
    """Stamp last_push_* + bump push_attempt_count; flip to failed when terminal."""
    safe_message = sanitize_push_error_for_storage(error_message)
    door_code.last_push_attempt_at = django_timezone.now()
    door_code.last_push_error = safe_message[:500]
    door_code.push_attempt_count = (door_code.push_attempt_count or 0) + 1
    if terminal:
        door_code.push_state = DoorCode.PushState.FAILED
    else:
        door_code.push_state = DoorCode.PushState.PENDING
    door_code.save(
        update_fields=[
            "last_push_attempt_at",
            "last_push_error",
            "push_attempt_count",
            "push_state",
            "updated_at",
        ]
    )

    if terminal:
        DoorCodeEvent.objects.create(
            door_code=door_code,
            user=door_code.user,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={"action": "push", "reason": safe_message[:200]},
        )


def push_door_code_to_lock(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    zwavejs: ZwavejsGateway,
    actor_user=None,
    timeout_seconds: float = 5.0,
) -> PushResult:
    """Program ``door_code``'s PIN onto ``lock_entity_id``.

    Allocates the lowest-free slot, sends CC 99 ``set`` (and CC 78 schedule when
    the code carries a daily window), and persists the slot index + push state.
    If an earlier push of this code sent the PIN to a slot on this lock but
    couldn't confirm it, and that slot now reads back with the PIN, the slot is
    adopted instead of writing a new one.

    Errors:
      * :class:`InvalidPin` / :class:`LockSlotsFull` raise before any network call.
      * :class:`LockRejectedCode` — terminal; the PIN matches the lock's admin
        code (checked before the ``set``) or the post-set readback shows the
        lock didn't store it. The row is flipped to ``failed``.
      * :class:`LockUnreachable` — transient; the row stays ``pending`` and the
        scheduler will retry.
      * :class:`LockPushFailed` — terminal; the row is flipped to ``failed`` and a
        ``code_failed`` event is emitted.
    """
    pin = _decrypt_pin_or_raise(door_code)
    try:
        node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    except (LockSyncNotFound, LockSyncInvalidRequest) as exc:
        # Terminal config issue: the Entity row exists but has no usable Z-Wave JS
        # node_id (or the entity itself is missing). Operator must sync HA entities
        # first; retries will just rediscover the same problem. Record + flip the
        # row to FAILED so the UI surfaces last_push_error instead of stalling on
        # "pending sync" forever.
        _record_push_failure(door_code=door_code, error_message=str(exc), terminal=True)
        raise LockPushFailed(str(exc)) from exc

    lock_key = f"lock_sync:{lock_entity_id}"
    acquired, lock_id = _try_acquire_sync_lock(lock_key=lock_key)
    if not acquired:
        raise LockUnreachable("Another sync is in progress for this lock; will retry.")

    try:
        claimed_slots = _claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code)
        try:
            _raise_if_pin_matches_admin_code(
                zwavejs=zwavejs,
                node_id=node_id,
                pin=pin,
                timeout_seconds=timeout_seconds,
            )
            slot_index = _find_adoptable_attempted_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                pin=pin,
                timeout_seconds=timeout_seconds,
                claimed_slots=claimed_slots,
            )
            adopted_existing_slot = slot_index is not None
            if slot_index is None:
                slot_index = _enumerate_free_slot(
                    zwavejs=zwavejs,
                    node_id=node_id,
                    timeout_seconds=timeout_seconds,
                    claimed_slots=claimed_slots,
                )
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable, ZwavejsCommandValidationError) as exc:
            _record_push_failure(door_code=door_code, error_message=str(exc), terminal=True)
            raise LockPushFailed(str(exc)) from exc
        except LockSlotsFull:
            raise
        except LockRejectedCode as exc:
            _record_push_failure(door_code=door_code, error_message=str(exc), terminal=True)
            raise
        except LockPushFailed:
            raise
        except GatewayError as exc:
            _record_push_failure(
                door_code=door_code,
                error_message=f"{exc.__class__.__name__}: {exc}",
                terminal=False,
            )
            raise LockUnreachable("Lock is not reachable right now; will retry.") from exc

        logger.info(
            "%s door code id=%d to %s (node=%d slot=%d)",
            "Adopting existing slot for" if adopted_existing_slot else "Pushing",
            door_code.id,
            lock_entity_id,
            node_id,
            slot_index,
        )

        # Once the PIN may be in the slot (set sent, or slot adopted), a transient
        # failure records the slot so the retry can adopt it instead of writing
        # the PIN to a second slot.
        pin_sent_to_slot = adopted_existing_slot
        try:
            if not adopted_existing_slot:
                pin_sent_to_slot = True
                # Z-Wave JS CC 99 set signature is (userId, userIdStatus, userCode).
                # userIdStatus = 1 means "Occupied" (the code is active on the lock).
                # The server validator rejects 2-arg calls; passing only [slot, pin]
                # makes the PIN land where userIdStatus is expected.
                zwavejs.invoke_cc_api(
                    node_id=node_id,
                    command_class=CC_USER_CODE,
                    method_name="set",
                    args=[slot_index, 1, pin],
                    timeout_seconds=timeout_seconds,
                )
                # The set returning is not proof the lock kept the code (issue #107);
                # read the slot back before claiming it or pushing schedules to it.
                # That get also makes Z-Wave JS re-read the slot, so it doubles as
                # the cache refresh #106 added; no second get after the success stamp.
                _verify_user_code_slot(
                    zwavejs=zwavejs,
                    node_id=node_id,
                    slot_index=slot_index,
                    pin=pin,
                    timeout_seconds=timeout_seconds,
                )
            weekdays_pushed = _push_daily_repeating_schedule(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                door_code=door_code,
                timeout_seconds=timeout_seconds,
            )
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable, ZwavejsCommandValidationError) as exc:
            _record_push_failure(door_code=door_code, error_message=str(exc), terminal=True)
            raise LockPushFailed(str(exc)) from exc
        except LockRejectedCode as exc:
            if exc.clear_slot:
                _clear_slot_best_effort(
                    zwavejs=zwavejs,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    timeout_seconds=timeout_seconds,
                )
            _record_push_failure(door_code=door_code, error_message=str(exc), terminal=True)
            raise
        except GatewayError as exc:
            error_message = f"{exc.__class__.__name__}: {exc}"
            if pin_sent_to_slot:
                _record_unconfirmed_slot_attempt(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason=error_message,
                )
            _record_push_failure(door_code=door_code, error_message=error_message, terminal=False)
            raise LockUnreachable("Lock did not accept the code in time; will retry.") from exc

        # Success — claim the slot and stamp pushed state. Resetting the attempt
        # counter is important: the cap is on *consecutive* failures, so a single
        # successful push must zero the meter.
        try:
            # Savepoint so a unique-constraint hit doesn't poison an outer transaction.
            with transaction.atomic():
                DoorCodeLockAssignment.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id).update(
                    slot_index=slot_index
                )
        except IntegrityError as exc:
            # Another writer recorded this slot after we enumerated, so the lock
            # may now hold this PIN over that code's. Retrying would only park the
            # PIN in a second slot, so fail terminally for the operator to check.
            message = f"Slot {slot_index} on {lock_entity_id} was recorded for another door code during the push."
            _record_push_failure(door_code=door_code, error_message=message, terminal=True)
            raise LockPushFailed(message) from exc
        door_code.push_state = DoorCode.PushState.PUSHED
        door_code.last_push_attempt_at = django_timezone.now()
        door_code.last_push_error = ""
        door_code.push_attempt_count = 0
        door_code.save(
            update_fields=[
                "push_state",
                "last_push_attempt_at",
                "last_push_error",
                "push_attempt_count",
                "updated_at",
            ]
        )

        schedule_applied = bool(weekdays_pushed)
        DoorCodeEvent.objects.create(
            door_code=door_code,
            user=actor_user or door_code.user,
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata={
                "action": "pushed",
                "slot_index": slot_index,
                "schedule_applied": schedule_applied,
                **({"adopted_existing_slot": True} if adopted_existing_slot else {}),
            },
        )

        timestamp = django_timezone.now()
        try:
            from alarm.dispatcher import notify_entities_changed

            notify_entities_changed(
                source="lock_push",
                entity_ids=[lock_entity_id],
                changed_at=timestamp,
            )
        except Exception:
            logger.warning("Failed to notify dispatcher after push for %s", lock_entity_id, exc_info=True)

        return PushResult(
            lock_entity_id=lock_entity_id,
            node_id=node_id,
            slot_index=slot_index,
            schedule_applied=schedule_applied,
            weekdays_pushed=weekdays_pushed,
            timestamp=timestamp,
        )
    finally:
        _release_sync_lock(lock_key=lock_key, lock_id=lock_id)


def push_door_code_to_assigned_locks(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    actor_user=None,
    timeout_seconds: float = 5.0,
    only_unassigned: bool = True,
) -> tuple[list[PushResult], list[tuple[str, str]]]:
    """Push ``door_code`` to every lock it is assigned to.

    Returns ``(successes, failures)``. Failures is a list of ``(lock_entity_id, reason)``
    tuples; transient failures leave the row at ``pending`` for the scheduler.

    ``only_unassigned=True`` (the default) skips assignments that already carry a
    ``slot_index`` — used by the scheduler retry path to avoid re-pushing locks that
    succeeded in a previous attempt.

    ``push_state`` / ``last_push_error`` live on the shared DoorCode row, so each
    lock's push overwrites the previous lock's. The final state is derived after
    the loop instead: ``failed`` if any lock failed terminally (keeping that
    error), else ``pending`` if any lock failed or is still without a slot, else
    ``pushed``. One lock's success never hides another lock's failure.

    An inactive code is never pushed: it returns ``([], [])`` without touching the
    locks or the row (issue #138).
    """
    # Sorted in Python so the prefetch is kept and the push order is deterministic.
    assignments = sorted(door_code.lock_assignments.all(), key=lambda assignment: assignment.pk)
    successes: list[PushResult] = []
    failures: list[tuple[str, str]] = []
    terminal_error: str | None = None
    pending_error: str | None = None

    door_code.refresh_from_db(fields=["is_active", "push_state", "last_push_attempt_at", "last_push_error"])
    if not door_code.is_active:
        logger.info("Not pushing inactive door code id=%s", door_code.id)
        return successes, failures
    for assignment in assignments:
        if only_unassigned and assignment.slot_index is not None:
            continue
        attempt_marker = door_code.last_push_attempt_at
        try:
            result = push_door_code_to_lock(
                door_code=door_code,
                lock_entity_id=assignment.lock_entity_id,
                zwavejs=zwavejs,
                actor_user=actor_user,
                timeout_seconds=timeout_seconds,
            )
            successes.append(result)
        except (LockUnreachable, LockSlotsFull, LockPushFailed, InvalidPin) as exc:
            failures.append((assignment.lock_entity_id, str(exc)))
            door_code.refresh_from_db(fields=["push_state", "last_push_attempt_at", "last_push_error"])
            # Capture what this lock's failure recorded before a later lock overwrites it.
            # Some failures (slots full, invalid PIN) don't record anything.
            recorded = door_code.last_push_attempt_at != attempt_marker
            if recorded and door_code.push_state == DoorCode.PushState.FAILED:
                terminal_error = terminal_error or door_code.last_push_error or str(exc)
            else:
                pending_error = pending_error or (door_code.last_push_error if recorded else "") or str(exc)
        # Refresh push_state from DB — each push may have updated it.
        door_code.refresh_from_db(fields=["push_state", "last_push_attempt_at", "last_push_error"])

    if terminal_error is not None:
        final_state, final_error = DoorCode.PushState.FAILED, terminal_error
    elif not successes:
        # Nothing succeeded and nothing failed terminally: the per-lock records stand.
        settle_clear_failure_state(door_code=door_code)
        return successes, failures
    elif (
        pending_error is not None
        or door_code.lock_assignments.filter(slot_index__isnull=True).exists()
        or unresolved_clear_failures(door_code=door_code)
    ):
        final_state, final_error = DoorCode.PushState.PENDING, pending_error or ""
    else:
        final_state, final_error = DoorCode.PushState.PUSHED, ""

    if door_code.push_state != final_state or door_code.last_push_error != final_error:
        door_code.push_state = final_state
        door_code.last_push_error = final_error
        door_code.save(update_fields=["push_state", "last_push_error", "updated_at"])
    # A lock whose clear failed may still hold the PIN, so the code is never pushed then.
    settle_clear_failure_state(door_code=door_code)
    return successes, failures


def push_or_settle_after_clear_retry(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    actor_user=None,
) -> tuple[list[PushResult], list[tuple[str, str]]]:
    """After :func:`retry_failed_slot_clears`, push an active code to its locks without a slot.

    An inactive code is never pushed. It's marked ``pushed`` once no clear is
    outstanding, the same as a deactivate, since its locks then hold nothing.
    """
    door_code = DoorCode.objects.prefetch_related("lock_assignments").get(id=door_code.id)
    if not door_code.is_active:
        if not settle_clear_failure_state(door_code=door_code) and (
            door_code.push_state != DoorCode.PushState.PUSHED or door_code.last_push_error
        ):
            door_code.push_state = DoorCode.PushState.PUSHED
            door_code.last_push_error = ""
            door_code.push_attempt_count = 0
            door_code.save(update_fields=["push_state", "last_push_error", "push_attempt_count", "updated_at"])
        return [], []
    successes, failures = push_door_code_to_assigned_locks(
        door_code=door_code,
        zwavejs=zwavejs,
        actor_user=actor_user,
        only_unassigned=True,
    )
    if not failures:
        mark_pushed_if_settled(door_code=door_code)
    return successes, failures
