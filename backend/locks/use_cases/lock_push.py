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

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone as django_timezone
from integrations_zwavejs.manager import (
    ZwavejsClientUnavailable,
    ZwavejsCommandValidationError,
    ZwavejsNotConfigured,
)

from alarm.crypto import InvalidToken, SettingsEncryption
from config.domain_exceptions import ConflictError, GatewayError, ValidationError
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases.code_lifecycle import belongs_on_lock
from locks.use_cases.lock_config_sync import (
    CC_SCHEDULE_ENTRY_LOCK,
    CC_USER_CODE,
    LockBusy,
    _coerce_int,
    _is_confirmed_empty_status,
    _normalize_pin,
    _parse_user_code_status,
    _release_sync_lock,
    _resolve_lock_node_id,
    _try_acquire_sync_lock,
    clear_lock_user_code_slot,
    hold_lock_sync,
    sync_lock_deadline,
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
    tracks. ``holds_pin`` is set only when the readback showed the PIN itself,
    and ``holds_other`` only when it showed a different code.
    """

    def __init__(self, message: str, *, clear_slot: bool = False, holds_pin: bool = False, holds_other: bool = False):
        super().__init__(message)
        self.clear_slot = clear_slot
        self.holds_pin = holds_pin
        self.holds_other = holds_other


class LockCodeUnverified(GatewayError):
    """The slot could not be read back after the ``set``; transient, the scheduler retries."""

    gateway_name = "zwavejs"


class PushSuperseded(LockUnreachable):
    """The code changed while its push waited for the lock (deleted, turned off, lock dropped); nothing was sent."""


class PushInTransaction(RuntimeError):
    """A push was called inside a DB transaction someone else opened (issue #130). Raised in dev and tests only."""


def _in_outer_transaction() -> bool:
    """Whether this connection is inside a transaction a caller opened, ``TestCase``'s own aside.

    ``TestCase`` wraps every test in atomic blocks marked ``_from_testcase``, the
    same ones Django's ``atomic(durable=True)`` check lets through, so a push
    called straight from a test doesn't count. Autocommit turned off by hand
    with ``set_autocommit(False)`` does: that leaves ``in_atomic_block`` false
    and no atomic blocks, so it's caught by checking autocommit itself.
    """
    if connection.get_autocommit():
        return False
    blocks = connection.atomic_blocks
    return not blocks or not all(getattr(block, "_from_testcase", False) for block in blocks)


def _check_no_outer_transaction(*, door_code: DoorCode, lock_entity_id: str) -> None:
    """Refuse a push inside a caller's transaction in dev and tests, and log a warning in prod (issue #130).

    Back to back pushes only stay in separate slots because the slot write
    commits before the ``lock_sync:`` lock is let go. Inside an outer
    transaction it doesn't, so a push from another process reads the slots from
    before it, picks the same one and overwrites it on the lock before the
    unique constraint notices (#106). Checked before anything is sent.
    """
    if not _in_outer_transaction():
        return
    message = (
        f"Door code id={door_code.id} is being pushed to {lock_entity_id} inside an open DB transaction, "
        "so its slot won't be committed before the lock_sync lock is released."
    )
    if settings.DEBUG or getattr(settings, "IS_TESTING", False):
        raise PushInTransaction(message)
    logger.warning(message)


# DoorCode fields a push writes to the lock, re-read once the push holds the lock.
_PUSHED_FIELDS = ["encrypted_pin", "is_active", "days_of_week", "window_start", "window_end"]
# Never sent to the lock, but a code is only pushed between them (issue #145), so re-read too.
_VALIDITY_FIELDS = ["start_at", "end_at"]


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

    Only a slot whose ``userIdStatus`` is Available (0) is free. Messaging (3)
    and PassageMode (4) slots hold lock config, and 0xfe (status not available),
    a missing value or anything unrecognised isn't a verdict, so none of them
    get a PIN written over them (issue #168).

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

    # The lock's own value IDs, so the read uses its real CC 99 endpoint, like lock config sync.
    status_vid_by_slot: dict[int, dict] = {}
    for vid in cc99:
        key = _coerce_int(vid.get("propertyKey"))
        if vid.get("property") == "userIdStatus" and key is not None:
            status_vid_by_slot[key] = vid

    for slot_index in range(1, int(max_slots) + 1):
        if slot_index in claimed_slots:
            continue
        status_vid = status_vid_by_slot.get(slot_index) or {
            "commandClass": CC_USER_CODE,
            "property": "userIdStatus",
            "propertyKey": slot_index,
        }
        try:
            status_value = zwavejs.node_get_value(node_id=node_id, value_id=status_vid, timeout_seconds=timeout_seconds)
        except Exception:
            # Treat unknown status as occupied to avoid clobbering a real code.
            continue
        if _is_confirmed_empty_status(status_value):
            return slot_index

    raise LockSlotsFull("No user-code slot on this lock is Available.")


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
# CC 99 userIdStatus values for a slot the lock uses for its own config (issue #168).
_USER_ID_STATUS_CONFIG_USES = {3: "messaging", 4: "passage mode"}


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
    report Available right after the set). A Messaging (3) or PassageMode (4)
    slot is lock config, so it's rejected as holding something else
    (``holds_other``), which every caller leaves alone; 0xfe is still no answer.
    Raises :class:`LockCodeUnverified`
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
        config_use = _USER_ID_STATUS_CONFIG_USES.get(_coerce_int(status))
        if config_use is not None:
            # Lock config, not a user code and not empty (issue #168). Never ours to clear.
            raise LockRejectedCode(
                f"Lock reports slot {slot_index} as a {config_use} slot, not a user code.", holds_other=True
            )
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
                raise LockRejectedCode(
                    f"Lock did not store the code: slot {slot_index} holds a different code.", holds_other=True
                )
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
            raise LockRejectedCode(
                f"Lock did not store the code: slot {slot_index} holds a different code.", holds_other=True
            )
        return True

    raise LockCodeUnverified(f"Could not read back slot {slot_index} after {attempts} attempts ({last_reason}).")


# DoorCodeEvent metadata ``action`` for a push that sent the PIN to a slot but
# didn't get it confirmed. The slot is what a later retry may adopt.
_UNCONFIRMED_PUSH_ACTION = "push_unconfirmed"

# DoorCodeEvent metadata ``action`` (on a ``code_removed`` event) recorded once a
# cleanup has checked or cleared a ``push_unconfirmed`` slot, so the attempts for
# that lock and slot before it no longer count (issue #161). A ``clear_resolved``
# for the same lock and slot settles them too when the slot was emptied
# (``_SLOT_EMPTIED_OUTCOMES``), see ``_unsettled_unconfirmed_attempts``.
_UNCONFIRMED_RESOLVED_ACTION = "unconfirmed_resolved"

# ``clear_resolved`` outcomes after which the slot holds nothing of the code's,
# whatever PIN an earlier attempt sent there: it was cleared, or the lock is gone.
_SLOT_EMPTIED_OUTCOMES = frozenset({"cleared", "lock_missing"})


# Metadata key for the PIN a recorded slot is expected to hold, encrypted at rest
# like ``DoorCode.encrypted_pin``. The code's PIN may have changed since, so a later
# readback has to compare against this one. Never logged or returned decrypted.
_EXPECTED_PIN_KEY = "encrypted_pin"

# Metadata flag on a ``push_unconfirmed`` attempt the push's own readback accepted (PR #190 review).
_SLOT_VERIFIED_KEY = "slot_verified"


def _encrypt_expected_pin(pin: str | None) -> dict[str, str]:
    return {_EXPECTED_PIN_KEY: SettingsEncryption.get().encrypt(pin)} if pin else {}


def _decrypt_expected_pin(metadata: dict) -> str | None:
    """The PIN stored with :func:`_encrypt_expected_pin`, or ``None`` for older events or an unreadable value."""
    value = metadata.get(_EXPECTED_PIN_KEY) if isinstance(metadata, dict) else None
    if not value:
        return None
    try:
        plaintext = (SettingsEncryption.get().decrypt(str(value)) or "").strip()
    except (ValueError, InvalidToken, TypeError):
        return None
    return plaintext if plaintext.isdigit() else None


def _record_unconfirmed_slot_attempt(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    slot_index: int,
    reason: str,
    pin: str,
    slot_verified: bool = False,
) -> DoorCodeEvent:
    """Remember that ``slot_index`` on this lock may hold ``pin`` for this code (no schema change).

    ``slot_verified`` marks an attempt whose slot the push's own readback already
    accepted, recorded right before its final write (PR #190 review). On a lock
    that masks PINs a later readback of that slot can't show the PIN, so
    adoption and the cleanups count a masked occupied slot as this code's for
    those attempts only (:func:`_attempt_slot_counts_as_ours`).

    Only the newest attempt per slot counts, so an untagged attempt keeps the
    tag of the unsettled tagged one it would replace when both sent the same
    PIN (issue #123). The newer one says nothing that undoes that earlier
    readback, and dropping the tag would leave the PIN on a masked lock with
    nothing clearing it.
    """
    if not slot_verified:
        current = _unsettled_unconfirmed_attempts(door_code=door_code, lock_entity_id=lock_entity_id).get(
            int(slot_index)
        )
        slot_verified = (
            current is not None
            and bool(current[1].get(_SLOT_VERIFIED_KEY))
            and _decrypt_expected_pin(current[1]) == pin
        )
    return DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": _UNCONFIRMED_PUSH_ACTION,
            "slot_index": int(slot_index),
            "reason": sanitize_push_error_for_storage(reason)[:200],
            **_encrypt_expected_pin(pin),
            **({_SLOT_VERIFIED_KEY: True} if slot_verified else {}),
        },
    )


def _verified_attempt_slots(*, door_code: DoorCode, lock_entity_id: str) -> set[int]:
    """Unsettled attempt slots on this lock whose newest attempt was recorded with ``slot_verified``."""
    return {
        slot_index
        for slot_index, (_event_id, metadata) in _unsettled_unconfirmed_attempts(
            door_code=door_code, lock_entity_id=lock_entity_id
        ).items()
        if metadata.get(_SLOT_VERIFIED_KEY)
    }


def _attempt_slot_counts_as_ours(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_index: int,
    pin: str,
    timeout_seconds: float,
    slot_verified: bool,
) -> bool:
    """Read an unconfirmed attempt slot back; ``True`` when it holds ``pin``, enabled or disabled.

    For a ``slot_verified`` attempt a slot that reads back occupied with a code
    the lock won't show counts too, the rule :func:`_tracked_slot_may_hold_pin`
    uses for a tracked slot, since this push's own readback already accepted it
    (PR #190 review). A readable different code, an empty slot and a messaging or
    passage mode slot never count. :class:`LockCodeUnverified` and gateway
    errors propagate.
    """
    try:
        confirmed = _verify_user_code_slot(
            zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, pin=pin, timeout_seconds=timeout_seconds
        )
    except LockRejectedCode as exc:
        if exc.holds_pin:
            return True
        return slot_verified and not (exc.holds_other or exc.clear_slot)
    return confirmed or slot_verified


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

    Only attempts since the code's last successful push to this lock count, and
    not ones a cleanup has settled since, newest first, without duplicates or
    ``claimed_slots``.
    """
    return list(_unconfirmed_attempts(door_code=door_code, lock_entity_id=lock_entity_id, claimed_slots=claimed_slots))


def _unconfirmed_attempt_window(*, door_code: DoorCode, lock_entity_id: str):
    """The ``push_unconfirmed`` events for this code on this lock since its last successful push there."""
    events = DoorCodeEvent.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id)
    last_pushed_id = (
        events.filter(event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
    )
    attempts = events.filter(event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__action=_UNCONFIRMED_PUSH_ACTION)
    if last_pushed_id is not None:
        attempts = attempts.filter(id__gt=last_pushed_id)
    return attempts


def _unsettled_unconfirmed_attempts(*, door_code: DoorCode, lock_entity_id: str) -> dict[int, tuple[int, dict]]:
    """The newest in-window ``push_unconfirmed`` event per slot that no cleanup has settled since.

    Maps each slot to that event's ``(id, metadata)``, newest first. An
    ``unconfirmed_resolved`` marker for the same lock and slot settles every
    attempt recorded before it (issue #161), and so does a ``clear_resolved``
    whose slot was actually cleared or whose lock is gone. Any other
    ``clear_resolved`` (the slot didn't hold the failure's expected PIN, or
    another code tracks it) only says something about the PIN that failure
    expected, so it only settles attempts recorded before that failure. An
    attempt recorded after it was never checked and may hold a newer PIN (PR
    #167 review). A later attempt on a settled slot counts again.
    """
    settled_up_to: dict[int, int] = {}
    open_failure_since: dict[int, int] = {}
    markers = (
        DoorCodeEvent.objects.filter(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            metadata__action__in=[_UNCONFIRMED_RESOLVED_ACTION, _CLEAR_FAILED_ACTION, _CLEAR_RESOLVED_ACTION],
        )
        .order_by("id")
        .values_list("id", "metadata")
    )
    for event_id, metadata in markers:
        slot_index = _coerce_int(metadata.get("slot_index")) if isinstance(metadata, dict) else None
        if not slot_index:
            continue
        action = metadata.get("action")
        if action == _CLEAR_FAILED_ACTION:
            open_failure_since.setdefault(slot_index, event_id)
            continue
        settles = event_id
        if action == _CLEAR_RESOLVED_ACTION:
            failed_at = open_failure_since.pop(slot_index, None)
            if metadata.get("outcome") not in _SLOT_EMPTIED_OUTCOMES:
                if failed_at is None:
                    continue
                settles = failed_at
        settled_up_to[slot_index] = max(settled_up_to.get(slot_index, 0), settles)

    newest: dict[int, tuple[int, dict]] = {}
    attempts = _unconfirmed_attempt_window(door_code=door_code, lock_entity_id=lock_entity_id)
    for event_id, metadata in attempts.order_by("-id").values_list("id", "metadata"):
        if not isinstance(metadata, dict):
            continue
        slot_index = _coerce_int(metadata.get("slot_index"))
        if slot_index is None or slot_index <= 0 or slot_index in newest:
            continue
        newest[slot_index] = (event_id, metadata)
    return {
        slot_index: attempt for slot_index, attempt in newest.items() if settled_up_to.get(slot_index, 0) < attempt[0]
    }


def _unconfirmed_attempts(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    claimed_slots: set[int] | frozenset[int] = frozenset(),
) -> dict[int, str | None]:
    """Like :func:`_unconfirmed_attempt_slots`, mapping each slot to the PIN its newest attempt sent.

    The PIN is ``None`` for attempts recorded before it was stored.
    """
    return {
        slot_index: _decrypt_expected_pin(metadata)
        for slot_index, (_event_id, metadata) in _unsettled_unconfirmed_attempts(
            door_code=door_code, lock_entity_id=lock_entity_id
        ).items()
        if slot_index not in claimed_slots
    }


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
    readback must report the PIN itself; a masked readback doesn't count, except
    for a ``slot_verified`` attempt that sent this same PIN, whose slot the push
    already accepted before its final write rolled back (PR #190 review). Its
    slot is adopted when it reads back occupied and enabled with a masked code.
    :class:`LockCodeUnverified` propagates.
    """
    attempts = _unconfirmed_attempts(
        door_code=door_code,
        lock_entity_id=lock_entity_id,
        claimed_slots=claimed_slots,
    )
    verified = _verified_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id)
    for slot_index, attempted_pin in attempts.items():
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
        if confirmed or (slot_index in verified and attempted_pin == pin):
            return slot_index
    return None


def decrypt_pin_or_none(door_code: DoorCode) -> str | None:
    """Return the stored plaintext PIN, or ``None`` when it's missing or unreadable."""
    try:
        return _decrypt_pin_or_raise(door_code)
    except InvalidPin:
        return None


def unconfirmed_attempt_lock_entity_ids(*, door_code: DoorCode) -> list[str]:
    """Locks where ``door_code`` has an unconfirmed slot left to check, assigned now or not (issue #134), sorted.

    Only attempts still in their window and not settled by a cleanup count, so a
    lock whose slot was already checked or cleared (ie when it was dropped) stops
    being tied to the code (issue #161).
    """
    candidates = set(
        DoorCodeEvent.objects.filter(
            door_code=door_code,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata__action=_UNCONFIRMED_PUSH_ACTION,
        )
        .exclude(lock_entity_id="")
        .values_list("lock_entity_id", flat=True)
    )
    return sorted(
        lock_entity_id
        for lock_entity_id in candidates
        if _unsettled_unconfirmed_attempts(door_code=door_code, lock_entity_id=lock_entity_id)
    )


def affected_lock_entity_ids(*, door_code: DoorCode) -> set[str]:
    """Every lock an update or delete of ``door_code`` may send a clear or set to (issue #131).

    Its assigned locks, locks with a clear still outstanding, and locks with an
    unconfirmed push attempt on record.
    """
    locks = set(DoorCodeLockAssignment.objects.filter(door_code=door_code).values_list("lock_entity_id", flat=True))
    locks.update(f.lock_entity_id for f in unresolved_clear_failures(door_code=door_code))
    locks.update(unconfirmed_attempt_lock_entity_ids(door_code=door_code))
    return locks


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
    node) can't be retried and aren't recorded as events. ``expected_pin`` is the
    PIN the slot is expected to hold, which may not be the code's current one; it
    never goes into ``as_metadata`` or ``repr``. ``slot_verified`` is carried over
    from a ``slot_verified`` unconfirmed attempt (PR #190 review), so the retry
    still counts a masked readback as this code's after a later push to that lock
    has closed the attempt's window. Events from before it was stored read as
    ``False``.
    """

    lock_entity_id: str
    slot_index: int
    reason: str
    removing: bool = False
    unconfirmed: bool = False
    permanent: bool = False
    slot_verified: bool = False
    expected_pin: str | None = field(default=None, repr=False, compare=False)
    event_id: int | None = field(default=None, compare=False)

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
        .values_list("id", "lock_entity_id", "metadata")
    )
    for event_id, lock_entity_id, metadata in events:
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
                slot_verified=bool(metadata.get(_SLOT_VERIFIED_KEY)),
                expected_pin=_decrypt_expected_pin(metadata),
                event_id=event_id,
            )
        else:
            pending.pop(key, None)
    return list(pending.values())


def _unresolved_clear_failure(*, door_code: DoorCode, lock_entity_id: str, slot_index: int) -> ClearFailure | None:
    return next(
        (
            f
            for f in unresolved_clear_failures(door_code=door_code)
            if (f.lock_entity_id, f.slot_index) == (lock_entity_id, slot_index)
        ),
        None,
    )


def _create_clear_failed_event(*, door_code: DoorCode, failure: ClearFailure) -> None:
    DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=failure.lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": _CLEAR_FAILED_ACTION,
            "slot_index": int(failure.slot_index),
            "reason": failure.reason,
            **({"removing": True} if failure.removing else {}),
            **({"unconfirmed": True} if failure.unconfirmed else {}),
            **({_SLOT_VERIFIED_KEY: True} if failure.slot_verified else {}),
            **_encrypt_expected_pin(failure.expected_pin),
        },
    )


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
    expected_pin: str | None,
    removing: bool = False,
    unconfirmed: bool = False,
    slot_verified: bool = False,
) -> ClearFailure:
    """Log a failed clear and, unless it's permanent, record it on the lock so it gets retried.

    ``expected_pin`` is the PIN the slot holds (stored encrypted, since the code's
    PIN may change before the retry). One event per slot until it's settled; a
    repeat failure only adds an event when it changes the flags (a tracked slot
    that's now being dropped, say) or brings the first known expected PIN.
    ``slot_verified`` only means something for an ``unconfirmed`` slot, and once
    recorded for one it's kept.
    """
    described = describe_clear_failure(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, exc=exc
    )
    if described.permanent:
        return described

    current = _unresolved_clear_failure(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
    if current is not None:
        removing = removing or current.removing
        unconfirmed = unconfirmed and current.unconfirmed
        expected_pin = current.expected_pin or expected_pin
        slot_verified = slot_verified or current.slot_verified
    slot_verified = unconfirmed and slot_verified
    failure = ClearFailure(
        lock_entity_id=lock_entity_id,
        slot_index=slot_index,
        reason=described.reason,
        removing=removing,
        unconfirmed=unconfirmed,
        slot_verified=slot_verified,
        expected_pin=expected_pin,
    )
    if current is None or (
        current.removing,
        current.unconfirmed,
        current.slot_verified,
        bool(current.expected_pin),
    ) != (
        removing,
        unconfirmed,
        slot_verified,
        bool(expected_pin),
    ):
        _create_clear_failed_event(door_code=door_code, failure=failure)
    return failure


def cancel_pending_removal(*, door_code: DoorCode, lock_entity_id: str) -> None:
    """Keep a lock the code was still being dropped from: its failed clear no longer removes the assignment.

    The slot still gets cleared and the lock pushed again (the slot may hold an
    older PIN), it just isn't deleted once that works.
    """
    for failure in unresolved_clear_failures(door_code=door_code):
        if failure.lock_entity_id == lock_entity_id and failure.removing:
            _create_clear_failed_event(
                door_code=door_code,
                failure=ClearFailure(
                    lock_entity_id=failure.lock_entity_id,
                    slot_index=failure.slot_index,
                    reason=failure.reason,
                    unconfirmed=failure.unconfirmed,
                    slot_verified=failure.slot_verified,
                    expected_pin=failure.expected_pin,
                ),
            )


def resolve_clear_failure(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int, outcome: str
) -> ClearFailure | None:
    """Settle a recorded clear failure for this slot (if any) and return it."""
    current = _unresolved_clear_failure(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index)
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


def _slot_holds_pin(
    *,
    zwavejs: ZwavejsGateway,
    lock_entity_id: str,
    slot_index: int,
    pin: str | None,
    timeout_seconds: float,
    slot_verified: bool = False,
) -> bool:
    """Read the slot back; ``True`` only when it reports ``pin`` (enabled or disabled).

    A ``slot_verified`` attempt slot also counts when it reads back occupied with
    a masked code (:func:`_attempt_slot_counts_as_ours`).
    """
    if not pin:
        return False
    return _attempt_slot_counts_as_ours(
        zwavejs=zwavejs,
        node_id=_resolve_lock_node_id(lock_entity_id=lock_entity_id),
        slot_index=slot_index,
        pin=pin,
        timeout_seconds=timeout_seconds,
        slot_verified=slot_verified,
    )


def _held_by_another_code(*, door_code: DoorCode, lock_entity_id: str, slot_index: int) -> bool:
    return (
        DoorCodeLockAssignment.objects.filter(lock_entity_id=lock_entity_id, slot_index=slot_index)
        .exclude(door_code=door_code)
        .exists()
    )


def _retry_failed_slot_clear(
    *,
    door_code: DoorCode,
    failure: ClearFailure,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float,
) -> ClearFailure | None:
    """One clear for :func:`retry_failed_slot_clears`; returns the failure if it's still failing."""
    lock_entity_id, slot_index = failure.lock_entity_id, failure.slot_index
    tracked_here = DoorCodeLockAssignment.objects.filter(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
    ).exists()
    if _held_by_another_code(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index) or (
        failure.unconfirmed and tracked_here
    ):
        resolve_clear_failure(
            door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="tracked"
        )
        return None
    try:
        if not tracked_here:
            if not _slot_holds_pin(
                zwavejs=zwavejs,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                pin=failure.expected_pin or decrypt_pin_or_none(door_code),
                timeout_seconds=timeout_seconds,
                # Carried on the failure, since a later push to this lock closes the attempt's window.
                slot_verified=failure.unconfirmed and failure.slot_verified,
            ):
                forget_cleared_slot(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    outcome="not_holding_pin",
                )
                return None
            # Checked again after the readback, right before the clear: a slot
            # another code took meanwhile holds its PIN now, not this one's.
            if _held_by_another_code(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index):
                resolve_clear_failure(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="tracked"
                )
                return None
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
            return None
        logger.warning(
            "Retrying the clear of slot %d on %s for door code id=%s failed again",
            slot_index,
            lock_entity_id,
            door_code.id,
            exc_info=True,
        )
        return ClearFailure(
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            reason=_clear_error_reason(exc),
            removing=failure.removing,
            unconfirmed=failure.unconfirmed,
            slot_verified=failure.slot_verified,
        )
    forget_cleared_slot(door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared")
    return None


def retry_failed_slot_clears(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> list[ClearFailure]:
    """Retry the clears recorded by :func:`record_clear_failure`. Returns the ones still failing.

    A slot held by another code's assignment now is settled as ``tracked`` and
    never touched, as is an unconfirmed slot this code's assignment now tracks
    (it was adopted or overwritten with the current PIN). A slot this code still
    tracks is cleared as is. Any other slot is read back first and only cleared
    when it holds the PIN it was expected to hold (the code's current PIN for
    failures recorded before that was stored), else it's settled as
    ``not_holding_pin``. A cleared slot is forgotten (:func:`forget_cleared_slot`),
    so a kept lock gets pushed again and a dropped lock's assignment goes. A lock
    that can't be resolved any more is settled as ``lock_missing``. A failure
    still failing bumps ``push_attempt_count`` so the scheduler's attempt cap
    applies.

    Each lock's clears run while holding its ``lock_sync:`` lock (waiting for it,
    issue #131), and its failures are read again once it's held, since an update
    or delete may have settled them meanwhile. All the locks share one wait
    deadline, so a call waits at most :data:`SYNC_LOCK_WAIT_SECONDS` in total. A
    lock still busy at the deadline is returned as still failing but isn't
    counted toward the attempt cap, since nothing was tried on it.
    """
    still_failing: list[ClearFailure] = []
    attempted_and_failed = False
    deadline = sync_lock_deadline()
    failures = unresolved_clear_failures(door_code=door_code)
    for lock_entity_id in sorted({f.lock_entity_id for f in failures}):
        try:
            with hold_lock_sync([lock_entity_id], deadline=deadline):
                for failure in unresolved_clear_failures(door_code=door_code):
                    if failure.lock_entity_id != lock_entity_id:
                        continue
                    still = _retry_failed_slot_clear(
                        door_code=door_code, failure=failure, zwavejs=zwavejs, timeout_seconds=timeout_seconds
                    )
                    if still is not None:
                        still_failing.append(still)
                        attempted_and_failed = True
        except LockBusy as exc:
            logger.warning(
                "Skipping the clear retries on %s for door code id=%s: %s", lock_entity_id, door_code.id, exc
            )
            still_failing.extend(
                ClearFailure(
                    lock_entity_id=f.lock_entity_id,
                    slot_index=f.slot_index,
                    reason=_clear_error_reason(exc),
                    removing=f.removing,
                    unconfirmed=f.unconfirmed,
                    slot_verified=f.slot_verified,
                )
                for f in failures
                if f.lock_entity_id == lock_entity_id
            )

    if attempted_and_failed:
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
    """Clear slots an unconfirmed push of ``door_code`` may have left its PIN in.

    For deleting, deactivating or changing the PIN of a code that is still
    pending: its PIN may have landed in a slot latchpoint never recorded
    (``slot_index`` stays empty until the readback confirms), so the usual
    "clear assigned slots" pass misses it. Candidates are the same recorded
    attempts adoption uses. A slot is cleared only when it reads back holding the
    PIN that attempt sent (``pin``, the code's PIN before this change, for
    attempts recorded before that was stored), enabled or disabled; empty, masked
    or different codes are left alone. A slot that can't be checked or cleared is
    recorded with :func:`record_clear_failure` (``unconfirmed``, with that PIN)
    so it's retried. A lock latchpoint can't resolve to a Z-Wave node any more
    gives a ``permanent`` failure per slot instead (nothing recorded to retry,
    but the caller can still put it in its event, issue #134). Returns the slots
    cleared as ``{"lock_entity_id", "slot_index"}`` dicts and the failures.

    Each lock is checked while holding its ``lock_sync:`` lock (a no-op for a
    caller already holding it), and a slot is skipped if another code's
    assignment holds it by the time it would be cleared (issue #131).
    """
    cleared: list[dict[str, object]] = []
    failed: list[ClearFailure] = []
    deadline = sync_lock_deadline()
    for lock_entity_id in dict.fromkeys(lock_entity_ids):
        with hold_lock_sync([lock_entity_id], deadline=deadline):
            lock_cleared, lock_failed = _clear_unconfirmed_slots_on_lock(
                door_code=door_code,
                pin=pin,
                lock_entity_id=lock_entity_id,
                zwavejs=zwavejs,
                timeout_seconds=timeout_seconds,
            )
        cleared.extend(lock_cleared)
        failed.extend(lock_failed)
    return cleared, failed


def _settle_unconfirmed_slot(*, door_code: DoorCode, lock_entity_id: str, slot_index: int, outcome: str) -> None:
    """Record that an unconfirmed slot was checked or cleared, so its attempts stop counting (issue #161).

    Settles a recorded clear failure for the slot if there is one, and adds an
    ``unconfirmed_resolved`` marker unless that failure's ``clear_resolved``
    already settles the attempts (the slot was emptied). The caller checked the
    slot against its newest attempt, so the marker covers every attempt so far.
    """
    resolved = resolve_clear_failure(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome=outcome
    )
    if resolved is not None and outcome in _SLOT_EMPTIED_OUTCOMES:
        return
    DoorCodeEvent.objects.create(
        door_code=door_code,
        user=door_code.user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_REMOVED,
        metadata={"action": _UNCONFIRMED_RESOLVED_ACTION, "slot_index": int(slot_index), "outcome": outcome},
    )


def _clear_unconfirmed_slots_on_lock(
    *,
    door_code: DoorCode,
    pin: str,
    lock_entity_id: str,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float,
    skip_slots: set[int] | frozenset[int] = frozenset(),
) -> tuple[list[dict[str, object]], list[ClearFailure]]:
    """One lock's part of :func:`clear_unconfirmed_slots_holding_pin`; the caller holds its lock.

    Every slot it checks or clears is settled with :func:`_settle_unconfirmed_slot`,
    as is one on a lock latchpoint can't resolve any more (``lock_missing``), so
    later updates and deletes don't keep coming back to it (issue #161). A slot
    whose check or clear fails transiently stays unsettled. ``skip_slots`` are
    left alone, and so is a slot with no PIN to compare against. A
    ``slot_verified`` attempt's slot is cleared when it reads back occupied with
    a masked code too (:func:`_attempt_slot_counts_as_ours`).
    """
    cleared: list[dict[str, object]] = []
    failed: list[ClearFailure] = []
    attempts = {
        slot_index: attempted_pin
        for slot_index, attempted_pin in _unconfirmed_attempts(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            claimed_slots=_claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code),
        ).items()
        if slot_index not in skip_slots and (attempted_pin or pin)
    }
    if not attempts:
        return cleared, failed
    verified = _verified_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id)
    try:
        node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    except Exception as exc:
        logger.warning("Can't resolve %s to check unconfirmed door code slots %s", lock_entity_id, list(attempts))
        for slot_index, attempted_pin in attempts.items():
            failure = record_clear_failure(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                exc=exc,
                expected_pin=attempted_pin or pin,
                unconfirmed=True,
                slot_verified=slot_index in verified,
            )
            failed.append(failure)
            if failure.permanent:
                _settle_unconfirmed_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
        return cleared, failed
    for slot_index, attempted_pin in attempts.items():
        expected_pin = attempted_pin or pin
        try:
            holds_pin = _attempt_slot_counts_as_ours(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                pin=expected_pin,
                timeout_seconds=timeout_seconds,
                slot_verified=slot_index in verified,
            )
            if not holds_pin:
                _settle_unconfirmed_slot(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    outcome="not_holding_pin",
                )
                continue
            if slot_index in _claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code):
                # Another code took this slot during the readback, so what it holds is that code's PIN.
                _settle_unconfirmed_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="tracked"
                )
                continue
            clear_lock_user_code_slot(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                zwavejs=zwavejs,
                timeout_seconds=timeout_seconds,
            )
            cleared.append({"lock_entity_id": lock_entity_id, "slot_index": slot_index})
            _settle_unconfirmed_slot(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
            )
        except Exception as exc:
            logger.warning(
                "Could not check/clear unconfirmed slot %d on %s for door code id=%s; it may still hold the PIN",
                slot_index,
                lock_entity_id,
                door_code.id,
            )
            failure = record_clear_failure(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                exc=exc,
                expected_pin=expected_pin,
                unconfirmed=True,
                slot_verified=slot_index in verified,
            )
            failed.append(failure)
            if failure.permanent:
                _settle_unconfirmed_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
    return cleared, failed


def inactive_slots_to_clear(
    *, door_code: DoorCode, failures: list[ClearFailure] | None = None
) -> list[tuple[str, int]]:
    """``(lock_entity_id, slot_index)`` pairs an inactive manual code may still have its PIN in (issue #158).

    That's its tracked slots, and the unconfirmed attempt slots on its locks that
    are still in their window and unsettled, skipping slots another code holds
    and slots with no PIN to compare against. Slots with an unresolved clear
    failure aren't listed, since :func:`retry_failed_slot_clears` handles those
    (pass ``failures`` when they're already loaded). Always empty for an active
    code, and for a synced one, whose slots are the lock's own.
    """
    if door_code.is_active or door_code.source == DoorCode.Source.SYNCED:
        return []
    return _slots_that_may_hold_pin(door_code=door_code, failures=failures)


def _slots_that_may_hold_pin(
    *, door_code: DoorCode, failures: list[ClearFailure] | None = None
) -> list[tuple[str, int]]:
    """The tracked and unconfirmed slots :func:`inactive_slots_to_clear` describes, for any code."""
    if failures is None:
        failures = unresolved_clear_failures(door_code=door_code)
    failing = {(f.lock_entity_id, f.slot_index) for f in failures}
    pin = decrypt_pin_or_none(door_code)
    slots: list[tuple[str, int]] = []
    assignments = (
        DoorCodeLockAssignment.objects.filter(door_code=door_code)
        .order_by("lock_entity_id")
        .values_list("lock_entity_id", "slot_index")
    )
    for lock_entity_id, tracked_slot in assignments:
        found = [int(tracked_slot)] if tracked_slot is not None else []
        attempts = _unconfirmed_attempts(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            claimed_slots=_claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code),
        )
        found.extend(slot_index for slot_index, attempted_pin in attempts.items() if attempted_pin or pin)
        slots.extend(
            (lock_entity_id, slot_index)
            for slot_index in dict.fromkeys(found)
            if (lock_entity_id, slot_index) not in failing
        )
    return slots


def pending_slot_clears(*, door_code: DoorCode, failures: list[ClearFailure] | None = None) -> list[dict[str, object]]:
    """The slot clears still outstanding for ``door_code``, for the API (issue #151). Never includes a PIN.

    Its unresolved clear failures, plus for an inactive manual code the slots
    :func:`inactive_slots_to_clear` finds, which the scheduler and Retry will
    clear. Sorted by lock and slot.
    """
    if failures is None:
        failures = unresolved_clear_failures(door_code=door_code)
    entries = {
        (f.lock_entity_id, f.slot_index): {
            "lock_entity_id": f.lock_entity_id,
            "slot_index": f.slot_index,
            "removing": f.removing,
        }
        for f in failures
    }
    for lock_entity_id, slot_index in inactive_slots_to_clear(door_code=door_code, failures=failures):
        entries.setdefault(
            (lock_entity_id, slot_index),
            {"lock_entity_id": lock_entity_id, "slot_index": slot_index, "removing": False},
        )
    return [entries[key] for key in sorted(entries)]


def _tracked_slot_may_hold_pin(
    *, zwavejs: ZwavejsGateway, lock_entity_id: str, slot_index: int, pin: str | None, timeout_seconds: float
) -> bool:
    """Read a slot an inactive code tracks back before clearing it (PR #167 review).

    ``True`` when it holds ``pin`` (enabled or disabled), or reads back occupied
    with a code that can't be read, which counts as this code's since it tracks
    the slot. ``False`` when it holds a different readable code (ie one typed in
    on the keypad since) or reads back empty. A code whose own PIN can't be read
    has nothing to compare against, so its slot counts as its own.
    :class:`LockCodeUnverified` and gateway errors propagate.
    """
    if not pin:
        return True
    try:
        _verify_user_code_slot(
            zwavejs=zwavejs,
            node_id=_resolve_lock_node_id(lock_entity_id=lock_entity_id),
            slot_index=slot_index,
            pin=pin,
            timeout_seconds=timeout_seconds,
        )
    except LockRejectedCode as exc:
        if exc.holds_pin:
            return True
        # A different code, or empty (the only rejection that asks for a clear
        # without holding the PIN). Disabled with an unreadable code stays ours.
        return not (exc.holds_other or exc.clear_slot)
    return True


def _clear_inactive_slots_on_lock(
    *,
    door_code: DoorCode,
    lock_entity_id: str,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float,
) -> list[ClearFailure]:
    """One lock's part of :func:`clear_inactive_code_slots`; the caller holds its lock."""
    failing = {
        f.slot_index for f in unresolved_clear_failures(door_code=door_code) if f.lock_entity_id == lock_entity_id
    }
    pin = decrypt_pin_or_none(door_code)
    failed: list[ClearFailure] = []
    assignment = DoorCodeLockAssignment.objects.filter(
        door_code=door_code, lock_entity_id=lock_entity_id, slot_index__isnull=False
    ).first()
    holds_pin: bool | None = None
    if assignment is not None and assignment.slot_index not in failing:
        slot_index = int(assignment.slot_index)
        try:
            holds_pin = _tracked_slot_may_hold_pin(
                zwavejs=zwavejs,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                pin=pin,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            # Not recorded: a recorded failure on a tracked slot is retried as a
            # clear with no readback, so this one stays a slot to read back first.
            failure = describe_clear_failure(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, exc=exc
            )
            failed.append(failure)
            if failure.permanent:
                forget_cleared_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
        if holds_pin is False:
            # Someone typed another code into it, or it's empty: nothing of ours to clear.
            forget_cleared_slot(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="not_holding_pin"
            )
    if holds_pin:
        slot_index = int(assignment.slot_index)
        try:
            clear_lock_user_code_slot(
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                zwavejs=zwavejs,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            failure = record_clear_failure(
                door_code=door_code,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                exc=exc,
                expected_pin=pin,
            )
            failed.append(failure)
            if failure.permanent:
                forget_cleared_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="lock_missing"
                )
        else:
            forget_cleared_slot(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
            )
    _, unconfirmed_failed = _clear_unconfirmed_slots_on_lock(
        door_code=door_code,
        pin=pin or "",
        lock_entity_id=lock_entity_id,
        zwavejs=zwavejs,
        timeout_seconds=timeout_seconds,
        skip_slots=failing,
    )
    failed.extend(unconfirmed_failed)
    return failed


def clear_inactive_code_slots(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> list[ClearFailure]:
    """Clear the slots :func:`inactive_slots_to_clear` finds, for the scheduler and Retry (issue #158).

    A slot the code tracks is read back first, since nothing has written to it
    for a while (ie rows from before #144) and a keypad code may have replaced
    the PIN: it's cleared when it holds this code's PIN or a code that can't be
    read, and forgotten without a clear when it holds a different code or reads
    back empty (:func:`_tracked_slot_may_hold_pin`). A readback that gets no
    answer isn't recorded, so the next try reads it back again. An unconfirmed
    slot is read back and only cleared when it holds the PIN that attempt sent,
    then settled (:func:`_clear_unconfirmed_slots_on_lock`). A slot another code
    holds is never touched. A clear that fails is recorded with
    :func:`record_clear_failure` so :func:`retry_failed_slot_clears` takes over.
    Either failure counts toward the attempt cap. A lock latchpoint can't
    resolve any more is settled as ``lock_missing``.

    Each lock is handled while holding its ``lock_sync:`` lock (one deadline
    shared across them), and the code is read again once it's held, so a code
    turned back on or deleted meanwhile is left alone. Returns the clears still
    outstanding, including those on a lock still busy at the deadline, which
    don't count toward the cap since nothing was tried there.
    """
    still_failing: list[ClearFailure] = []
    attempted_and_failed = False
    deadline = sync_lock_deadline()
    slots = inactive_slots_to_clear(door_code=door_code)
    for lock_entity_id in sorted({lock for lock, _slot in slots}):
        try:
            with hold_lock_sync([lock_entity_id], deadline=deadline):
                try:
                    door_code.refresh_from_db(fields=["is_active", "source", "encrypted_pin"])
                except DoorCode.DoesNotExist:
                    return still_failing
                if door_code.is_active or door_code.source == DoorCode.Source.SYNCED:
                    return still_failing
                failed = _clear_inactive_slots_on_lock(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    zwavejs=zwavejs,
                    timeout_seconds=timeout_seconds,
                )
        except LockBusy as exc:
            logger.warning(
                "Skipping the slot clears on %s for inactive door code id=%s: %s", lock_entity_id, door_code.id, exc
            )
            still_failing.extend(
                ClearFailure(lock_entity_id=lock, slot_index=slot_index, reason=_clear_error_reason(exc))
                for lock, slot_index in slots
                if lock == lock_entity_id
            )
            continue
        transient = [f for f in failed if not f.permanent]
        still_failing.extend(transient)
        attempted_and_failed = attempted_and_failed or bool(transient)

    if attempted_and_failed:
        door_code.refresh_from_db(fields=["push_attempt_count"])
        door_code.push_attempt_count = (door_code.push_attempt_count or 0) + 1
        door_code.last_push_attempt_at = django_timezone.now()
        door_code.save(update_fields=["push_attempt_count", "last_push_attempt_at", "updated_at"])
    return still_failing


def slots_to_withdraw(*, door_code: DoorCode) -> list[tuple[str, int]]:
    """``(lock_entity_id, slot_index)`` pairs an active code may have its PIN in before its start (issue #145).

    The same slots :func:`inactive_slots_to_clear` finds for an inactive code:
    tracked ones and unsettled unconfirmed ones, without slots another code
    holds or that already have a clear failure on record for the retries.
    """
    if not door_code.is_active:
        return []
    return _slots_that_may_hold_pin(door_code=door_code)


def withdraw_slots_before_start(
    *,
    door_code: DoorCode,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 5.0,
) -> tuple[list[dict[str, object]], list[ClearFailure]]:
    """Clear what :func:`slots_to_withdraw` finds; the caller holds every lock's ``lock_sync:`` lock.

    A tracked slot is cleared as is and forgotten, the way a schedule change
    clears it before the re-push. An unconfirmed slot is read back and only
    cleared when it holds the PIN that attempt sent, then settled
    (:func:`_clear_unconfirmed_slots_on_lock`). A clear that fails is recorded
    with :func:`record_clear_failure` so :func:`retry_failed_slot_clears` takes
    over, and a lock latchpoint can't resolve any more is forgotten as
    ``lock_missing``. Returns the slots cleared and the failures.
    """
    failing = {(f.lock_entity_id, f.slot_index) for f in unresolved_clear_failures(door_code=door_code)}
    pin = decrypt_pin_or_none(door_code)
    cleared: list[dict[str, object]] = []
    failed: list[ClearFailure] = []
    assignments = DoorCodeLockAssignment.objects.filter(door_code=door_code).order_by("lock_entity_id")
    for lock_entity_id, tracked_slot in assignments.values_list("lock_entity_id", "slot_index"):
        if tracked_slot is not None and (lock_entity_id, int(tracked_slot)) not in failing:
            slot_index = int(tracked_slot)
            try:
                clear_lock_user_code_slot(
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    zwavejs=zwavejs,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                failure = record_clear_failure(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    exc=exc,
                    expected_pin=pin,
                )
                failed.append(failure)
                if failure.permanent:
                    forget_cleared_slot(
                        door_code=door_code,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                        outcome="lock_missing",
                    )
            else:
                cleared.append({"lock_entity_id": lock_entity_id, "slot_index": slot_index})
                forget_cleared_slot(
                    door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="cleared"
                )
        lock_cleared, lock_failed = _clear_unconfirmed_slots_on_lock(
            door_code=door_code,
            pin=pin or "",
            lock_entity_id=lock_entity_id,
            zwavejs=zwavejs,
            timeout_seconds=timeout_seconds,
            skip_slots={slot for lock, slot in failing if lock == lock_entity_id},
        )
        cleared.extend(lock_cleared)
        failed.extend(lock_failed)
    return cleared, failed


def retained_marker_event_ids(*, older_than: datetime) -> set[int]:
    """Ids of events older than ``older_than`` that event retention must keep (issue #139).

    Those are a code's unresolved ``clear_failed`` events (the newest per slot,
    which carries its flags and expected PIN) and its unsettled
    ``push_unconfirmed`` events (the newest per slot still in the window since
    its last successful push to that lock). Pruning either would forget a slot
    that may still hold a PIN. Settled markers, including attempts a cleanup has
    checked or cleared (issue #161), and markers whose code is gone, aren't kept.
    """
    old_markers = DoorCodeEvent.objects.filter(
        created_at__lt=older_than,
        door_code__isnull=False,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata__action__in=[_CLEAR_FAILED_ACTION, _UNCONFIRMED_PUSH_ACTION],
    )
    keep: set[int] = set()
    for door_code in DoorCode.objects.filter(id__in=old_markers.values("door_code_id")):
        keep.update(f.event_id for f in unresolved_clear_failures(door_code=door_code) if f.event_id is not None)
        lock_entity_ids = (
            old_markers.filter(door_code=door_code, metadata__action=_UNCONFIRMED_PUSH_ACTION)
            .values_list("lock_entity_id", flat=True)
            .distinct()
        )
        for lock_entity_id in lock_entity_ids:
            keep.update(
                event_id
                for event_id, _metadata in _unsettled_unconfirmed_attempts(
                    door_code=door_code, lock_entity_id=lock_entity_id
                ).values()
            )
    return keep


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


def _validate_schedule_or_raise(door_code: DoorCode) -> None:
    """Raise :class:`InvalidPin` when :func:`_push_daily_repeating_schedule` would reject the code's window.

    Checked before the ``set`` (issue #123), so a window that got past the
    serializer fails before the PIN is on the lock instead of after it. Same
    conditions as the schedule push: no ``days_of_week`` means no schedule, and
    a missing start or end falls back to the full day.
    """
    if door_code.days_of_week is None or not (door_code.window_start and door_code.window_end):
        return
    _compute_schedule_duration(door_code.window_start, door_code.window_end)


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
    event_metadata: dict[str, object] | None = None,
    lock_entity_id: str = "",
) -> None:
    """Stamp last_push_* + bump push_attempt_count; flip to failed when terminal.

    ``event_metadata`` is added to the ``code_failed`` event a terminal failure
    records, and ``lock_entity_id`` is set on it.
    """
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
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={"action": "push", "reason": safe_message[:200], **(event_metadata or {})},
        )


def _fail_slot_recorded_for_another_code(
    *, door_code: DoorCode, lock_entity_id: str, slot_index: int
) -> LockPushFailed:
    """Record the push whose slot write hit ``door_code_lock_assignments_unique_lock_slot`` (issues #109, #129).

    The lock may now hold this PIN in ``slot_index`` in place of the code the DB
    has there, so the error and the ``code_failed`` event name that code and say
    what to do next (also kept whole in the event's ``next_step``, since its
    ``reason`` is cut at 200 characters). A code lock sync imported gets its PIN
    from whatever the slot holds on the next sync, so for one of those the next
    step is dropping this lock from this code once the sync reports the slot
    holding this PIN (its duplicate PIN flag), rather than a retry that would
    put it in a second slot.

    The ``push_unconfirmed`` attempt the push recorded for the slot right before
    its write stays, with this PIN, since the delete of it rolled back with the
    write. Every cleanup and
    adoption skips a slot another code holds, so it does nothing while that code
    has it, but if that code lets go of the slot without clearing it (ie a
    readback found this PIN there instead of its own), a delete or deactivate of
    this code reads it back and clears it, and a retry adopts it.
    """
    owner = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(lock_entity_id=lock_entity_id, slot_index=slot_index)
        .exclude(door_code=door_code)
        .first()
    )
    owner_code = owner.door_code if owner is not None else None
    if owner_code is None:
        holder = "another door code"
        in_place_of = "the code recorded there"
    else:
        label = f', "{owner_code.label}"' if owner_code.label else ""
        holder = f"another door code (id {owner_code.id}{label})"
        in_place_of = "that code's"
    if owner_code is not None and owner_code.source == DoorCode.Source.SYNCED:
        next_step = (
            f"That code was imported by a lock sync, so the next lock sync on {lock_entity_id} gives it "
            f"whatever PIN slot {slot_index} holds. Run one, and if it reports slot {slot_index} holding this "
            f"code's PIN, remove {lock_entity_id} from this code instead of retrying, since a retry puts the PIN "
            "in a second slot."
        )
    else:
        next_step = f"Run a lock sync on {lock_entity_id} to check what the slot holds before retrying."
    message = (
        f"Slot {slot_index} on {lock_entity_id} was recorded for {holder} during the push. "
        f"The lock may now hold this PIN in slot {slot_index} in place of {in_place_of}. {next_step}"
    )
    _record_push_failure(
        door_code=door_code,
        error_message=message,
        terminal=True,
        lock_entity_id=lock_entity_id,
        event_metadata={
            "slot_index": int(slot_index),
            "conflicting_door_code_id": owner_code.id if owner_code is not None else None,
            "conflicting_door_code_label": owner_code.label if owner_code is not None else None,
            "conflicting_door_code_source": owner_code.source if owner_code is not None else None,
            "lock_sync_needed": True,
            "next_step": sanitize_push_error_for_storage(next_step),
        },
    )
    return LockPushFailed(sanitize_push_error_for_storage(message))


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
      * :class:`InvalidPin` / :class:`LockSlotsFull` raise before any ``set``.
        :class:`InvalidPin` (a PIN that can't be read, or a schedule window
        that ends before it starts) is recorded as a terminal failure on this
        lock, since only an edit fixes it (issue #123). :class:`LockSlotsFull`
        is recorded as a transient failure, so the row stays ``pending`` and
        the scheduler's attempt cap applies.
      * :class:`LockRejectedCode` — terminal; the PIN matches the lock's admin
        code (checked before the ``set``) or the post-set readback shows the
        lock didn't store it. The row is flipped to ``failed``.
      * :class:`LockUnreachable` — transient; the row stays ``pending`` and the
        scheduler will retry.
      * :class:`LockPushFailed` — terminal; the row is flipped to ``failed`` and a
        ``code_failed`` event is emitted.
      * :class:`PushSuperseded` — once the lock is held the code turns out to be
        deleted, inactive, no longer on this lock, not started yet or expired
        (issue #145); nothing is sent or recorded.

    The code's PIN, schedule and assignment are read again once the
    ``lock_sync:`` lock is held, since a caller that loaded them earlier (the
    scheduler) may have waited behind an update or delete (issue #131). An
    assignment that has a slot by then is returned as is instead of being
    written to a second slot.

    Has to run in autocommit, so the slot is committed before the lock is let go
    (issue #130). Called inside a caller's transaction it raises
    :class:`PushInTransaction` in dev and tests and logs a warning in prod.
    """
    _check_no_outer_transaction(door_code=door_code, lock_entity_id=lock_entity_id)
    try:
        node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    except (LockSyncNotFound, LockSyncInvalidRequest) as exc:
        # Terminal config issue: the Entity row exists but has no usable Z-Wave JS
        # node_id (or the entity itself is missing). Operator must sync HA entities
        # first; retries will just rediscover the same problem. Record + flip the
        # row to FAILED so the UI surfaces last_push_error instead of stalling on
        # "pending sync" forever.
        _record_push_failure(door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id)
        raise LockPushFailed(str(exc)) from exc

    lock_key = f"lock_sync:{lock_entity_id}"
    acquired, lock_id = _try_acquire_sync_lock(lock_key=lock_key)
    if not acquired:
        raise LockUnreachable("Another sync is in progress for this lock; will retry.")

    try:
        try:
            door_code.refresh_from_db(fields=[*_PUSHED_FIELDS, *_VALIDITY_FIELDS])
        except DoorCode.DoesNotExist as exc:
            raise PushSuperseded("Door code was deleted before its push started.") from exc
        assignment = DoorCodeLockAssignment.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id).first()
        if not door_code.is_active or assignment is None:
            raise PushSuperseded("Door code is no longer active on this lock; nothing was pushed.")
        if not belongs_on_lock(door_code):
            # Its start_at moved into the future or it expired while the push waited (issue #145).
            raise PushSuperseded("Door code isn't valid right now (not started or expired); nothing was pushed.")
        if assignment.slot_index is not None:
            logger.info(
                "Door code id=%d already holds slot %d on %s; not pushing it again",
                door_code.id,
                assignment.slot_index,
                lock_entity_id,
            )
            return PushResult(lock_entity_id=lock_entity_id, node_id=node_id, slot_index=int(assignment.slot_index))
        try:
            pin = _decrypt_pin_or_raise(door_code)
            _validate_schedule_or_raise(door_code)
        except InvalidPin as exc:
            # Only an edit fixes the stored PIN or window, so this is terminal for
            # the lock: recorded and counted instead of pushed again every tick,
            # and nothing goes out, so a bad window never leaves an unscheduled PIN
            # on the lock (issue #123). Checked here, with the lock held and the
            # code read again, so a stale copy can't mark a fixed code failed.
            _record_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise

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
            _record_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise LockPushFailed(str(exc)) from exc
        except LockSlotsFull as exc:
            # Counted like any transient failure, so a lock with nothing Available
            # ends up failed at the attempt cap instead of retried forever.
            _record_push_failure(door_code=door_code, error_message=str(exc), terminal=False)
            raise
        except LockRejectedCode as exc:
            _record_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
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

        # Once the PIN may be in the slot (set sent, or slot adopted), a gateway
        # failure, transient or a terminal Z-Wave JS one, records the slot so the
        # retry can adopt it instead of writing the PIN to a second slot.
        pin_sent_to_slot = adopted_existing_slot
        # The set returned (or the slot was adopted). The terminal Z-Wave JS errors
        # below are raised before anything is sent, so one from the set itself
        # means the PIN never went out, and one after it means it did.
        set_returned = adopted_existing_slot
        # Whether a readback in this push accepted the slot: the post-set one, or
        # the adoption readback for an adopted slot.
        slot_accepted = adopted_existing_slot
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
                set_returned = True
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
                slot_accepted = True
            weekdays_pushed = _push_daily_repeating_schedule(
                zwavejs=zwavejs,
                node_id=node_id,
                slot_index=slot_index,
                door_code=door_code,
                timeout_seconds=timeout_seconds,
            )
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable, ZwavejsCommandValidationError) as exc:
            if set_returned:
                # The PIN may be in the slot, so keep it on record like a transient
                # failure does, or nothing would clear it on a delete (issue #123).
                # Tagged slot_verified only once a readback accepted the slot, so a
                # masked readback later counts as ours only then.
                _record_unconfirmed_slot_attempt(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason=f"{exc.__class__.__name__}: {exc}",
                    pin=pin,
                    slot_verified=slot_accepted,
                )
            _record_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise LockPushFailed(str(exc)) from exc
        except LockRejectedCode as exc:
            if exc.clear_slot:
                _clear_slot_best_effort(
                    zwavejs=zwavejs,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    timeout_seconds=timeout_seconds,
                )
            _record_push_failure(
                door_code=door_code, error_message=str(exc), terminal=True, lock_entity_id=lock_entity_id
            )
            raise
        except GatewayError as exc:
            error_message = f"{exc.__class__.__name__}: {exc}"
            if pin_sent_to_slot:
                # Tagged like the terminal branch above: only once a readback in
                # this push accepted the slot (a schedule timeout, or an adopted slot).
                _record_unconfirmed_slot_attempt(
                    door_code=door_code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason=error_message,
                    pin=pin,
                    slot_verified=slot_accepted,
                )
            _record_push_failure(door_code=door_code, error_message=error_message, terminal=False)
            raise LockUnreachable("Lock did not accept the code in time; will retry.") from exc

        # Success — claim the slot and stamp pushed state. Resetting the attempt
        # counter is important: the cap is on *consecutive* failures, so a single
        # successful push must zero the meter.
        schedule_applied = bool(weekdays_pushed)
        # The PIN is in the slot now, so record it as an unconfirmed attempt first.
        # In autocommit (the only way a push runs, see _check_no_outer_transaction)
        # it commits on its own, so if the block below rolls back (the process dies,
        # a DB error, or the unique constraint) the slot isn't lost: a retry adopts
        # it and a delete or deactivate reads it back and clears it. It's tagged
        # slot_verified, since the readback above accepted the slot, so that holds
        # on a lock that masks PINs too. A clean commit deletes it again, so a
        # successful push leaves no failure in the audit log.
        pending_marker = _record_unconfirmed_slot_attempt(
            door_code=door_code,
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            reason="PIN set on the lock, slot not saved yet",
            pin=pin,
            slot_verified=True,
        )
        try:
            # One transaction for the slot, the pushed stamp and its event (issue
            # #130), so a process that dies between them can't leave the code
            # pending with a slot, which the scheduler never retries. A savepoint
            # inside an outer transaction, so a unique-constraint hit doesn't poison it.
            with transaction.atomic():
                DoorCodeLockAssignment.objects.filter(door_code=door_code, lock_entity_id=lock_entity_id).update(
                    slot_index=slot_index
                )
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
                pending_marker.delete()
        except IntegrityError as exc:
            # Another writer recorded this slot after we enumerated, so the lock
            # may now hold this PIN over that code's. Retrying would only park the
            # PIN in a second slot, so fail terminally for the operator to check.
            raise _fail_slot_recorded_for_another_code(
                door_code=door_code, lock_entity_id=lock_entity_id, slot_index=slot_index
            ) from exc

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
    locks or the row (issue #138). Neither is one before its ``start_at`` or from
    its ``end_at`` on (issue #145). ``enforce_door_code_validity`` pushes it once
    it starts and retires it once it expires.
    """
    # Sorted in Python so the prefetch is kept and the push order is deterministic.
    assignments = sorted(door_code.lock_assignments.all(), key=lambda assignment: assignment.pk)
    successes: list[PushResult] = []
    failures: list[tuple[str, str]] = []
    terminal_error: str | None = None
    pending_error: str | None = None

    door_code.refresh_from_db(
        fields=["is_active", "push_state", "last_push_attempt_at", "last_push_error", *_VALIDITY_FIELDS]
    )
    if not door_code.is_active:
        logger.info("Not pushing inactive door code id=%s", door_code.id)
        return successes, failures
    if not belongs_on_lock(door_code):
        logger.info("Not pushing door code id=%s outside its start_at/end_at", door_code.id)
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
        except PushSuperseded:
            # An update or delete got the lock first and settled the code's locks
            # and state itself, so this stale pass stops here.
            logger.info("Door code id=%s changed while its push waited for the lock; stopping", door_code.id)
            return successes, failures
        except (LockUnreachable, LockSlotsFull, LockPushFailed, InvalidPin) as exc:
            failures.append((assignment.lock_entity_id, str(exc)))
            door_code.refresh_from_db(fields=["push_state", "last_push_attempt_at", "last_push_error"])
            # Capture what this lock's failure recorded before a later lock overwrites it.
            # Some failures (a lock another sync holds) don't record anything.
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

    An inactive code is never pushed. Whatever it may still have on its locks
    with no clear failure on record (a tracked slot, or an unconfirmed attempt
    slot) is cleared first (:func:`clear_inactive_code_slots`, issue #158), and
    those still outstanding come back as the failures. It's marked ``pushed``
    once nothing is left to clear, the same as a deactivate, since its locks
    then hold nothing.
    """
    door_code = DoorCode.objects.prefetch_related("lock_assignments").get(id=door_code.id)
    if not door_code.is_active:
        still_failing = clear_inactive_code_slots(door_code=door_code, zwavejs=zwavejs)
        failures = [(f.lock_entity_id, f.reason) for f in still_failing]
        # The clear may have waited behind an update that turned the code back on
        # (PR #167 review). That update owns its state now, so nothing below may
        # write over it, and the writes only land while the code is still off.
        try:
            door_code.refresh_from_db(fields=["is_active", "push_state", "last_push_error"])
        except DoorCode.DoesNotExist:
            return [], failures
        if door_code.is_active:
            return [], failures
        still_off = DoorCode.objects.filter(id=door_code.id, is_active=False)
        if settle_clear_failure_state(door_code=door_code):
            pass
        elif still_failing:
            # A lock still busy, or a readback that got no answer, leaves a slot
            # behind with nothing recorded.
            error = sanitize_push_error_for_storage(clear_failures_message(still_failing))[:500]
            if (door_code.push_state, door_code.last_push_error) != (DoorCode.PushState.PENDING, error):
                still_off.update(
                    push_state=DoorCode.PushState.PENDING, last_push_error=error, updated_at=django_timezone.now()
                )
        elif door_code.push_state != DoorCode.PushState.PUSHED or door_code.last_push_error:
            still_off.update(
                push_state=DoorCode.PushState.PUSHED,
                last_push_error="",
                push_attempt_count=0,
                updated_at=django_timezone.now(),
            )
        return [], failures
    successes, failures = push_door_code_to_assigned_locks(
        door_code=door_code,
        zwavejs=zwavejs,
        actor_user=actor_user,
        only_unassigned=True,
    )
    if not failures:
        mark_pushed_if_settled(door_code=door_code)
    return successes, failures
