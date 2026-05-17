"""Programs door-code PINs and CC 78 schedules onto physical Z-Wave JS locks (ADR 0092).

The companion to ``lock_config_sync.sync_lock_config`` (pull-sync). Whereas
pull-sync reads the lock and reconciles into the DB, ``push_door_code_to_lock``
takes a saved ``DoorCode`` row, picks the lowest free slot on the target lock,
sends CC 99 ``set`` (user code) + an optional CC 78 ``setDailyRepeatingSchedule``
per weekday, and records the slot assignment + push state.

The use case is intended to be called synchronously from the create/update API
paths. It commits as much progress as it makes; transient failures land the row
at ``push_state="pending"`` for the scheduler to retry.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

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
    _parse_user_code_status,
    _release_sync_lock,
    _resolve_lock_node_id,
    _try_acquire_sync_lock,
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

# Weekday bit -> Z-Wave JS weekday integer (1=Monday .. 7=Sunday).
# Mirrors the read path's _weekday_to_mask_index inversion.
_WEEKDAY_BIT_TO_ZWAVE = {
    0: 1,  # Monday
    1: 2,
    2: 3,
    3: 4,
    4: 5,
    5: 6,
    6: 7,  # Sunday
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
) -> int:
    """Return the lowest free user-code slot on the node. Raises :class:`LockSlotsFull`."""
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
    """Push CC 78 daily-repeating schedule for each enabled weekday. Returns ZW weekday ints used."""
    if door_code.days_of_week is None or not door_code.window_start or not door_code.window_end:
        return []

    duration_h, duration_m = _compute_schedule_duration(door_code.window_start, door_code.window_end)
    if duration_h == 0 and duration_m == 0:
        return []

    weekdays_pushed: list[int] = []
    for bit, zwave_weekday in _WEEKDAY_BIT_TO_ZWAVE.items():
        if not (int(door_code.days_of_week) & (1 << bit)):
            continue
        slot_id = bit + 1
        payload = {
            "userId": slot_index,
            "slotId": slot_id,
            "startHour": door_code.window_start.hour,
            "startMinute": door_code.window_start.minute,
            "durationHour": duration_h,
            "durationMinute": duration_m,
            "weekdays": [zwave_weekday],
        }
        zwavejs.invoke_cc_api(
            node_id=node_id,
            command_class=CC_SCHEDULE_ENTRY_LOCK,
            method_name="setDailyRepeatingSchedule",
            args=[payload],
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

    Errors:
      * :class:`InvalidPin` / :class:`LockSlotsFull` raise before any network call.
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
        try:
            slot_index = _enumerate_free_slot(
                zwavejs=zwavejs,
                node_id=node_id,
                timeout_seconds=timeout_seconds,
            )
        except (ZwavejsNotConfigured, ZwavejsClientUnavailable, ZwavejsCommandValidationError) as exc:
            _record_push_failure(door_code=door_code, error_message=str(exc), terminal=True)
            raise LockPushFailed(str(exc)) from exc
        except LockSlotsFull:
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
            "Pushing door code id=%d to %s (node=%d slot=%d)",
            door_code.id,
            lock_entity_id,
            node_id,
            slot_index,
        )

        try:
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
        except GatewayError as exc:
            _record_push_failure(
                door_code=door_code,
                error_message=f"{exc.__class__.__name__}: {exc}",
                terminal=False,
            )
            raise LockUnreachable("Lock did not accept the code in time; will retry.") from exc

        # Success — claim the slot and stamp pushed state. Resetting the attempt
        # counter is important: the cap is on *consecutive* failures, so a single
        # successful push must zero the meter.
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
    """
    assignments = list(door_code.lock_assignments.all())
    successes: list[PushResult] = []
    failures: list[tuple[str, str]] = []

    for assignment in assignments:
        if only_unassigned and assignment.slot_index is not None:
            continue
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
        # Refresh push_state from DB — each push may have updated it.
        door_code.refresh_from_db(fields=["push_state", "last_push_attempt_at", "last_push_error"])

    if successes and not failures:
        door_code.push_state = DoorCode.PushState.PUSHED
        door_code.last_push_error = ""
        door_code.save(update_fields=["push_state", "last_push_error", "updated_at"])
    return successes, failures
