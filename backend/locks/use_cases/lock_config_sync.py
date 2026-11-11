from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import threading
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any

from django.db import IntegrityError, connection, transaction
from django.utils import timezone as django_timezone

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.gateways.zwavejs import ZwavejsGateway
from alarm.models import Entity
from config.domain_exceptions import ConflictError, NotFoundError, ValidationError
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment

logger = logging.getLogger(__name__)

# Z-Wave command class IDs
CC_USER_CODE = 99
CC_SCHEDULE_ENTRY_LOCK = 78  # 0x4E


class NotFound(NotFoundError):
    pass


class InvalidRequest(ValidationError):
    pass


class SyncInProgress(ConflictError):
    pass


class LockBusy(SyncInProgress):
    """Waited too long for another operation on a lock to finish (issue #131)."""


@dataclass
class SlotSyncResult:
    slot_index: int
    action: str
    door_code_id: int | None = None
    pin_known: bool | None = None
    is_active: bool | None = None
    schedule_applied: bool = False
    schedule_unsupported: bool = False
    schedule: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    # Other door codes on this lock whose PIN this slot also holds (issue #140).
    duplicate_pin_door_code_ids: list[int] = field(default_factory=list)


@dataclass
class SyncResult:
    lock_entity_id: str
    node_id: int
    slots: list[SlotSyncResult]
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    deactivated: int = 0
    errors: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "lock_entity_id": self.lock_entity_id,
            "node_id": self.node_id,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "deactivated": self.deactivated,
            "errors": self.errors,
            "timestamp": self.timestamp.isoformat(),
            "slots": [
                {
                    "slot_index": row.slot_index,
                    "action": row.action,
                    "door_code_id": row.door_code_id,
                    "pin_known": row.pin_known,
                    "is_active": row.is_active,
                    "schedule_applied": row.schedule_applied,
                    "schedule_unsupported": row.schedule_unsupported,
                    "schedule": row.schedule,
                    "warnings": row.warnings,
                    "error": row.error,
                    "duplicate_pin_door_code_ids": row.duplicate_pin_door_code_ids,
                }
                for row in self.slots
            ],
        }


_in_flight_lock = threading.Lock()
_in_flight_keys: set[str] = set()
# Per-thread hold counts for the in-process guard, so it's re-entrant like a
# Postgres session advisory lock (each thread has its own DB connection).
_held_by_thread = threading.local()

# How long door code update / delete and the slot clears wait for another
# operation on the same lock (a push, a config sync) before giving up. Longer
# than a queued push can hold the lock: its 30s budget (PUSH_LOCK_BUDGET_SECONDS
# in lock_push), a readback sleep of up to 2s that started before the budget ran
# out and its DB writes. So an edit or delete right after a create waits for that
# push instead of answering 409 (issue #203).
SYNC_LOCK_WAIT_SECONDS = 45.0
_SYNC_LOCK_POLL_SECONDS = (0.05, 1.0)  # first delay, cap


def _pg_lock_id(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Keep within signed BIGINT range.
    return int.from_bytes(digest[:8], "big", signed=False) & 0x7FFF_FFFF_FFFF_FFFF


def _thread_hold_counts() -> dict[str, int]:
    counts = getattr(_held_by_thread, "counts", None)
    if counts is None:
        counts = _held_by_thread.counts = {}
    return counts


def _try_acquire_sync_lock(*, lock_key: str) -> tuple[bool, int | None]:
    """
    Best-effort per-lock concurrency guard. Re-entrant: a caller that already
    holds ``lock_key`` gets it again and has to release it once per acquire.

    - Postgres: pg_try_advisory_lock (cross-process; session locks stack per connection).
    - Other DBs: in-process guard only, counted per thread.
    """
    if connection.vendor == "postgresql":
        lock_id = _pg_lock_id(lock_key)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_id])
            acquired = bool(cursor.fetchone()[0])
        return acquired, lock_id

    counts = _thread_hold_counts()
    if counts.get(lock_key):
        counts[lock_key] += 1
        return True, None
    with _in_flight_lock:
        if lock_key in _in_flight_keys:
            return False, None
        _in_flight_keys.add(lock_key)
    counts[lock_key] = 1
    return True, None


def _release_sync_lock(*, lock_key: str, lock_id: int | None) -> None:
    if connection.vendor == "postgresql" and lock_id is not None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [int(lock_id)])
        except Exception:
            logger.warning("Failed to release advisory lock %s for key %s", lock_id, lock_key, exc_info=True)
        return

    counts = _thread_hold_counts()
    remaining = counts.get(lock_key, 0) - 1
    if remaining > 0:
        counts[lock_key] = remaining
        return
    counts.pop(lock_key, None)
    with _in_flight_lock:
        _in_flight_keys.discard(lock_key)


def _acquire_sync_lock_waiting(*, lock_key: str, deadline: float) -> int | None:
    """Like :func:`_try_acquire_sync_lock` but retries with backoff until ``deadline`` (monotonic).

    Raises :class:`LockBusy` when the lock is still held elsewhere at the deadline.
    """
    delay, max_delay = _SYNC_LOCK_POLL_SECONDS
    while True:
        acquired, lock_id = _try_acquire_sync_lock(lock_key=lock_key)
        if acquired:
            return lock_id
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            lock_entity_id = lock_key.removeprefix("lock_sync:")
            raise LockBusy(f"Another operation on {lock_entity_id} is still running. Try again in a moment.")
        _time.sleep(min(delay, remaining))
        delay = min(delay * 2, max_delay)


def sync_lock_deadline(timeout_seconds: float | None = None) -> float:
    """A ``time.monotonic()`` deadline for :func:`hold_lock_sync`, :data:`SYNC_LOCK_WAIT_SECONDS` away by default.

    Compute it once per request and pass it to every hold in that request, so
    all of its waits together stay within the limit.
    """
    return _time.monotonic() + (SYNC_LOCK_WAIT_SECONDS if timeout_seconds is None else timeout_seconds)


@contextlib.contextmanager
def hold_lock_sync(lock_entity_ids, *, deadline: float | None = None):
    """Hold ``lock_sync:<lock>`` for every lock in ``lock_entity_ids``, waiting for each (issue #131).

    Locks are taken in sorted order so two callers that need overlapping locks
    can't deadlock, and released in reverse. Waiting stops at ``deadline`` (a
    ``time.monotonic()`` value from :func:`sync_lock_deadline`, a fresh one
    when omitted) and :class:`LockBusy` is raised with nothing left held.
    Re-entrant, so a caller that already holds a lock (or a push nested
    inside) just stacks on it and the outer hold stays until the outer block exits.
    """
    if deadline is None:
        deadline = sync_lock_deadline()
    held: list[tuple[str, int | None]] = []
    try:
        for lock_entity_id in sorted({str(e) for e in lock_entity_ids if e}):
            lock_key = f"lock_sync:{lock_entity_id}"
            held.append((lock_key, _acquire_sync_lock_waiting(lock_key=lock_key, deadline=deadline)))
        yield
    finally:
        for lock_key, lock_id in reversed(held):
            _release_sync_lock(lock_key=lock_key, lock_id=lock_id)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            return None
        return str(int(value))
    return str(value)


def _parse_user_code_status(value: object) -> tuple[bool, bool | None]:
    """
    Return (occupied, is_active).

    Known Z-Wave JS CC 99 mapping:
    - 0: Available
    - 1: Occupied/Enabled
    - 2: Occupied/Disabled
    - 254: Status not available
    """
    status_int = _coerce_int(value)
    if status_int is not None:
        if status_int == 0:
            return False, None
        if status_int == 1:
            return True, True
        if status_int == 2:
            return True, False
        return False, None

    if isinstance(value, str):
        text = value.strip().lower()
        if "available" in text:
            return False, None
        if "occupied" in text and "enabled" in text:
            return True, True
        if "occupied" in text and "disabled" in text:
            return True, False
        if "occupied" in text:
            return True, None

    return False, None


def _is_confirmed_empty_status(value: object) -> bool:
    """Whether a CC 99 ``userIdStatus`` says the slot is Available (0), not just "not occupied".

    254 (status not available), a missing value or anything else unrecognised
    isn't a verdict, so a code tracked in that slot is left alone (issue #149).
    """
    status_int = _coerce_int(value)
    if status_int is not None:
        return status_int == 0
    return isinstance(value, str) and value.strip().lower() == "available"


def _normalize_pin(raw: object) -> tuple[bool, str | None]:
    """
    Return (pin_known, normalized_pin).

    Masked/unknown PINs are returned as (False, None).
    """
    text = _coerce_str(raw)
    if text is None:
        return False, None
    text = text.strip()
    if not text:
        return False, None

    # Common mask patterns ("****", "••••", etc).
    if len(set(text)) == 1 and text[0] in {"*", "•", "x", "X"}:
        return False, None

    if not text.isdigit():
        return False, None
    if len(text) < 4 or len(text) > 8:
        return False, None
    return True, text


def _parse_schedule_key(property_key: object) -> tuple[int | None, int | None, int | None]:
    """
    Best-effort extraction of (user_id, weekday, schedule_slot) from propertyKey.

    Z-Wave JS schedule keys vary by lock/firmware; we support common dict/JSON/string patterns.
    """
    if isinstance(property_key, dict):
        user_id = _coerce_int(
            property_key.get("userId")
            or property_key.get("user_id")
            or property_key.get("user")
            or property_key.get("codeSlot")
        )
        weekday = _coerce_int(
            property_key.get("weekday")
            or property_key.get("weekDay")
            or property_key.get("day")
            or property_key.get("dayOfWeek")
        )
        slot = _coerce_int(
            property_key.get("slot")
            or property_key.get("slotId")
            or property_key.get("slot_id")
            or property_key.get("scheduleSlot")
        )
        return user_id, weekday, slot

    if isinstance(property_key, str):
        text = property_key.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                obj = json.loads(text)
            except Exception:
                obj = None
            if isinstance(obj, dict):
                return _parse_schedule_key(obj)

        nums = [int(n) for n in re.findall(r"\d+", text)]
        if len(nums) >= 3:
            return nums[0], nums[1], nums[2]
        if len(nums) == 2:
            return nums[0], nums[1], None
        if len(nums) == 1:
            return nums[0], None, None

    if isinstance(property_key, int):
        return property_key, None, None

    return None, None, None


def _weekday_to_mask_index(weekday: int) -> int | None:
    """
    Convert a Z-Wave weekday to LatchPoint's mask index where Monday=0..Sunday=6.

    CC 78 ScheduleEntryLockWeekday encodes Sunday=0..Saturday=6; some sources use
    1=Monday..7=Sunday. (weekday - 1) % 7 maps both: 0->Sun(6), 1->Mon(0),
    6->Sat(5), 7->Sun(6).
    """
    if 0 <= weekday <= 7:
        return (weekday - 1) % 7
    return None


def _get_present(value: dict[str, Any], *keys: str) -> object:
    for key in keys:
        if key in value:
            return value.get(key)
    return None


def _parse_schedule_entry(value: object) -> tuple[time, time] | None:
    """
    Parse a schedule entry dict into (start, end) times.
    Returns None for empty/unset entries.
    """
    if not isinstance(value, dict):
        return None

    start_h = _coerce_int(_get_present(value, "startHour", "start_hour"))
    start_m = _coerce_int(_get_present(value, "startMinute", "start_minute"))
    if start_h is None or start_m is None:
        return None

    duration_h = _coerce_int(_get_present(value, "durationHour", "duration_hour", "durationHours", "duration_hours"))
    duration_m = _coerce_int(
        _get_present(value, "durationMinute", "duration_minute", "durationMinutes", "duration_minutes")
    )
    if duration_h is not None or duration_m is not None:
        duration_h = duration_h or 0
        duration_m = duration_m or 0
        total_minutes = int(duration_h) * 60 + int(duration_m)
        if total_minutes <= 0:
            return None
        start_dt = datetime(2000, 1, 1, int(start_h), int(start_m), tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(minutes=total_minutes)
        if end_dt.date() != start_dt.date():
            return None
        return start_dt.timetz().replace(tzinfo=None), end_dt.timetz().replace(tzinfo=None)

    end_h = _coerce_int(_get_present(value, "endHour", "end_hour", "stopHour", "stop_hour"))
    end_m = _coerce_int(_get_present(value, "endMinute", "end_minute", "stopMinute", "stop_minute"))
    if end_h is None or end_m is None:
        return None
    start_t = time(int(start_h), int(start_m))
    end_t = time(int(end_h), int(end_m))
    if end_t <= start_t:
        return None
    return start_t, end_t


def _extract_weekday_schedule_windows(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    value_ids: list[dict[str, Any]],
    slot_indices: set[int],
    timeout_seconds: float = 10.0,
) -> tuple[dict[int, dict[str, Any] | None], dict[int, str]]:
    """
    Return:
    - schedule_by_slot: slot_index -> {"days_of_week": int, "window_start": "HH:MM:SS",
      "window_end": "HH:MM:SS"} or None
    - unsupported_by_slot: slot_index -> reason
    """
    weekday_value_ids: list[dict[str, Any]] = []
    unsupported_value_ids: list[dict[str, Any]] = []

    for value_id in value_ids:
        if not isinstance(value_id, dict):
            continue
        if value_id.get("commandClass") != CC_SCHEDULE_ENTRY_LOCK:
            continue
        prop = value_id.get("property")
        if not isinstance(prop, str) or not prop:
            continue
        prop_l = prop.lower()
        if "weekday" in prop_l and "schedule" in prop_l:
            weekday_value_ids.append(value_id)
            continue
        if ("yearday" in prop_l and "schedule" in prop_l) or ("daily" in prop_l and "schedule" in prop_l):
            unsupported_value_ids.append(value_id)

    # If no CC 78 schedule value IDs exist in the cache, fall back to direct CC API
    # invocation for daily repeating schedules (ADR 0081).
    if not weekday_value_ids and not unsupported_value_ids:
        return _extract_daily_repeating_schedule_windows_via_cc_api(
            zwavejs=zwavejs,
            node_id=node_id,
            slot_indices=slot_indices,
            timeout_seconds=timeout_seconds,
        )

    # Weekday windows aggregated by slot -> weekday -> list[(start,end)]
    windows: dict[int, dict[int, list[tuple[time, time]]]] = {}
    unsupported_by_slot: dict[int, str] = {}

    for value_id in weekday_value_ids:
        prop_key = value_id.get("propertyKey")
        user_id, weekday, _schedule_slot = _parse_schedule_key(prop_key)
        if user_id is None or user_id not in slot_indices:
            continue
        day_idx = _weekday_to_mask_index(int(weekday)) if weekday is not None else None
        if day_idx is None:
            continue

        try:
            raw_value = zwavejs.node_get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)
        except Exception as exc:
            unsupported_by_slot.setdefault(user_id, f"Failed to read schedule: {exc.__class__.__name__}")
            continue

        # Normalize to list of entry dicts.
        entries: list[dict[str, Any]] = []
        if isinstance(raw_value, dict):
            # Sometimes a single entry, sometimes a mapping of entries.
            if any(
                k in raw_value
                for k in ("startHour", "start_hour", "durationHour", "duration_hour", "endHour", "end_hour")
            ):
                entries = [raw_value]
            else:
                for v in raw_value.values():
                    if isinstance(v, dict):
                        entries.append(v)
        elif isinstance(raw_value, list):
            entries = [v for v in raw_value if isinstance(v, dict)]
        else:
            continue

        parsed: list[tuple[time, time]] = []
        for entry in entries:
            window = _parse_schedule_entry(entry)
            if window is None:
                continue
            parsed.append(window)

        if not parsed:
            continue

        windows.setdefault(int(user_id), {}).setdefault(int(day_idx), []).extend(parsed)

    # Any unsupported schedule types present -> mark relevant slots as unsupported (best-effort).
    for value_id in unsupported_value_ids:
        user_id, _weekday, _slot = _parse_schedule_key(value_id.get("propertyKey"))
        if user_id is None or user_id not in slot_indices:
            continue
        unsupported_by_slot.setdefault(int(user_id), "Unsupported schedule type present on lock.")

    schedule_by_slot: dict[int, dict[str, Any] | None] = {}

    for slot_index in slot_indices:
        if slot_index in unsupported_by_slot:
            schedule_by_slot[slot_index] = None
            continue

        by_day = windows.get(slot_index, {})
        if not by_day:
            schedule_by_slot[slot_index] = None
            continue

        # Must be at most one window per weekday.
        normalized: dict[int, tuple[time, time]] = {}
        multi = False
        for day_idx, day_windows in by_day.items():
            uniq = list({(w[0], w[1]) for w in day_windows})
            if len(uniq) != 1:
                multi = True
                break
            normalized[day_idx] = uniq[0]
        if multi or not normalized:
            unsupported_by_slot.setdefault(slot_index, "Multiple schedule windows per day are not supported.")
            schedule_by_slot[slot_index] = None
            continue

        # Must be same window across all selected weekdays.
        starts_ends = list(normalized.values())
        first = starts_ends[0]
        if any(w != first for w in starts_ends[1:]):
            unsupported_by_slot.setdefault(slot_index, "Different schedule windows per weekday are not supported.")
            schedule_by_slot[slot_index] = None
            continue

        days_mask = 0
        for day_idx in normalized:
            days_mask |= 1 << int(day_idx)

        schedule_by_slot[slot_index] = {
            "days_of_week": int(days_mask),
            "window_start": first[0].strftime("%H:%M:%S"),
            "window_end": first[1].strftime("%H:%M:%S"),
        }

    return schedule_by_slot, unsupported_by_slot


def _extract_daily_repeating_schedule_windows_via_cc_api(
    *,
    zwavejs: ZwavejsGateway,
    node_id: int,
    slot_indices: set[int],
    timeout_seconds: float = 10.0,
) -> tuple[dict[int, dict[str, Any] | None], dict[int, str]]:
    """
    Read daily repeating schedules via invoke_cc_api (CC 78) for locks that
    don't expose schedule value IDs in the value cache (ADR 0081).

    Returns same structure as _extract_weekday_schedule_windows.
    """
    schedule_by_slot: dict[int, dict[str, Any] | None] = {}
    unsupported_by_slot: dict[int, str] = {}

    try:
        num_slots_result = zwavejs.invoke_cc_api(
            node_id=node_id,
            command_class=CC_SCHEDULE_ENTRY_LOCK,
            method_name="getNumSlots",
            args=[],
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        logger.warning("Failed to get schedule slot counts for node %d: %s", node_id, exc)
        return {si: None for si in slot_indices}, {
            si: f"Failed to query schedule slot counts: {exc.__class__.__name__}" for si in slot_indices
        }

    # The result may be wrapped in a "response" key depending on the server version.
    if isinstance(num_slots_result, dict) and "response" in num_slots_result:
        num_slots_result = num_slots_result["response"]
    if not isinstance(num_slots_result, dict):
        return {si: None for si in slot_indices}, {
            si: "Lock returned invalid getNumSlots response." for si in slot_indices
        }

    num_daily_slots = _coerce_int(num_slots_result.get("numDailyRepeatingSlots"))
    if not isinstance(num_daily_slots, int) or num_daily_slots <= 0:
        return {si: None for si in slot_indices}, {
            si: "Lock has 0 daily repeating schedule slots." for si in slot_indices
        }

    logger.info("Node %d: %d daily repeating schedule slots available", node_id, num_daily_slots)

    for user_id in sorted(slot_indices):
        days_mask = 0
        window: tuple[time, time] | None = None
        has_any_schedule = False
        user_error: str | None = None

        for slot_id in range(1, num_daily_slots + 1):
            try:
                response = zwavejs.invoke_cc_api(
                    node_id=node_id,
                    command_class=CC_SCHEDULE_ENTRY_LOCK,
                    method_name="getDailyRepeatingSchedule",
                    args=[{"userId": user_id, "slotId": slot_id}],
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                logger.debug(
                    "Failed to read daily schedule user=%d slot=%d node=%d: %s",
                    user_id,
                    slot_id,
                    node_id,
                    exc,
                )
                user_error = f"Schedule read failed: {exc.__class__.__name__}"
                break

            # Unwrap "response" envelope if present.
            if isinstance(response, dict) and "response" in response:
                response = response["response"]

            # Empty schedule: response is {}, None, or missing keys.
            if not response or not isinstance(response, dict):
                continue

            parsed = _parse_schedule_entry(response)
            if parsed is None:
                continue

            has_any_schedule = True
            start_t, end_t = parsed

            # All slots for this user must share the same time window.
            if window is None:
                window = (start_t, end_t)
            elif window != (start_t, end_t):
                user_error = "Different schedule windows across daily repeating slots."
                break

            # Build days bitmask from weekdays array (CC 78: Sunday=0 .. Saturday=6).
            weekdays = response.get("weekdays", [])
            if isinstance(weekdays, list):
                for wd in weekdays:
                    wd_int = _coerce_int(wd)
                    if wd_int is not None:
                        mask_idx = _weekday_to_mask_index(int(wd_int))
                        if mask_idx is not None:
                            days_mask |= 1 << mask_idx

        if user_error:
            unsupported_by_slot[user_id] = user_error
            schedule_by_slot[user_id] = None
        elif not has_any_schedule or days_mask == 0:
            schedule_by_slot[user_id] = None
        else:
            if window is None:  # pragma: no cover — guarded by has_any_schedule
                unsupported_by_slot[user_id] = "Schedule data inconsistency."
                schedule_by_slot[user_id] = None
                continue
            schedule_by_slot[user_id] = {
                "days_of_week": int(days_mask),
                "window_start": window[0].strftime("%H:%M:%S"),
                "window_end": window[1].strftime("%H:%M:%S"),
            }

    return schedule_by_slot, unsupported_by_slot


def clear_lock_user_code_slot(
    *,
    lock_entity_id: str,
    slot_index: int,
    zwavejs: ZwavejsGateway,
    timeout_seconds: float = 10.0,
) -> None:
    """Clear a user code slot on a physical Z-Wave JS lock (CC 99 clear).

    Holds ``lock_sync:<lock>`` for the clear, which is a no-op for a caller that
    already holds it and waits (raising :class:`LockBusy`) otherwise.
    """
    node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    with hold_lock_sync([lock_entity_id]):
        logger.info("Clearing user code slot %d on %s (node %d)", slot_index, lock_entity_id, node_id)
        zwavejs.invoke_cc_api(
            node_id=node_id,
            command_class=CC_USER_CODE,
            method_name="clear",
            args=[slot_index],
            timeout_seconds=timeout_seconds,
        )


def _resolve_lock_node_id(*, lock_entity_id: str) -> int:
    lock_entity_id = (lock_entity_id or "").strip()
    if not lock_entity_id:
        raise InvalidRequest("lock_entity_id is required.")

    entity = Entity.objects.filter(entity_id=lock_entity_id).first()
    if not entity:
        raise NotFound("Lock entity not found.")

    attrs = getattr(entity, "attributes", {}) or {}
    zw = attrs.get("zwavejs") if isinstance(attrs, dict) else None
    node_id = zw.get("node_id") if isinstance(zw, dict) else None
    node_id = _coerce_int(node_id)
    if not isinstance(node_id, int) or node_id <= 0:
        raise InvalidRequest("Lock entity is not linked to a Z-Wave JS node. Sync Home Assistant entities first.")
    return int(node_id)


# DoorCodeEvent metadata ``action`` for a slot the sync left alone instead of
# importing it (issue #150). Recorded as ``code_failed`` rather than
# ``code_synced`` because a ``code_synced`` event on the lock ends the code's
# ``push_unconfirmed`` window (see ``lock_push._unconfirmed_attempt_window``).
_SYNC_SKIPPED_ACTION = "sync_skipped"

# ``SlotSyncResult.warnings`` entries for a skipped slot.
_SKIP_CLEAR_OUTSTANDING = "clear_outstanding"
_SKIP_INACTIVE_MANUAL_CODE = "inactive_code_on_lock"
_SKIP_PIN_MISMATCH = "pin_mismatch"
_SKIP_SCHEDULE_PENDING = "schedule_pending"
# An active manual code's tracked slot the cache called Available, but a live
# readback didn't answer Available twice, so the code keeps the slot (issue #166).
# Also a synced code's slot on the lock it was imported from, when the code is
# on other locks too: it isn't turned off or let go of (issue #221).
_SKIP_SLOT_NOT_CONFIRMED_EMPTY = "slot_not_confirmed_empty"
# Same, but this lock may already have the code's PIN in another slot, so
# pushing it again would add a copy or fail (PR #214 review).
_SKIP_PIN_IN_ANOTHER_SLOT = "pin_in_another_slot"
# A synced code's added lock flagged to be brought in line with the code (issue #220).
_SKIP_UPDATE_PENDING = "update_pending"
_WARN_DUPLICATE_PIN = "duplicate_pin"
# An active manual code whose slot holds its PIN but reads Occupied/Disabled.
# Latchpoint owns a manual code, so the sync doesn't turn it off (issue #166).
_WARN_DISABLED_ON_LOCK = "disabled_on_lock"
# An active manual code whose tracked slot read back empty: the slot is let go
# and the code goes pending so the scheduler pushes it again (issue #166).
_WARN_SLOT_EMPTY_REPUSH = "slot_empty_repush"
# A synced code that's on other locks too, whose slot here holds a new PIN a
# live readback didn't confirm. The PIN isn't taken, so a stale read never goes
# out to those locks, and the next sync tries again (issue #220).
_WARN_PIN_CHANGE_UNCONFIRMED = "pin_change_unconfirmed"
# The same for a new schedule (or one removed) a live CC 78 read didn't confirm (issue #220).
_WARN_SCHEDULE_CHANGE_UNCONFIRMED = "schedule_change_unconfirmed"
# The new PIN or schedule taken from this slot was queued for the code's other locks (issue #220).
_WARN_SENT_TO_OTHER_LOCKS = "sent_to_other_locks"
# Another code on one of those locks already has the new PIN, so only the old
# one is cleared there and the code is off that lock until the other is deleted (issues #188, #220).
_WARN_PIN_HELD_ON_OTHER_LOCK = "pin_held_on_other_lock"
# A synced code that's on other locks too, whose slot here the cache calls
# disabled, but two live reads didn't both say so. It stays on, so a stale read
# never takes its PIN off those locks (issue #221).
_WARN_OFF_CHANGE_UNCONFIRMED = "off_change_unconfirmed"
# This slot was confirmed disabled (or empty) by two live reads, so the code is
# off and its PIN is being taken off the code's other locks (issue #221).
_WARN_TAKING_OFF_OTHER_LOCKS = "taking_off_other_locks"


def _has_outstanding_slot_cleanup(*, door_code: DoorCode, lock_entity_id: str) -> bool:
    """Whether a slot may still hold an older PIN of ``door_code``: a clear that hasn't
    gone through yet (#144) or an unconfirmed push still in its window (#111).

    Clear failures count on any lock, since the scheduler retries every one of
    them. That keeps a code latchpoint is turning off, or giving a new PIN, from
    being turned back on or given its old PIN by a stale read of a lock whose
    clear already went through, while another lock's clear is still failing
    (PR #165). Bringing a synced code's added locks in line after a change from
    the lock it was imported from never records one (issue #220,
    :mod:`locks.use_cases.added_lock_reconcile`), so it can't hold that lock back.
    Unconfirmed attempts only count on the lock being synced, and only the
    ones a cleanup would still act on: not settled since (#161), not in a slot
    another code holds, and with a PIN to compare against. An attempt left on a
    lock the code was dropped from before #167 has nothing coming to settle it,
    so counting it would stop the code's sync on every other lock for good.
    """
    from locks.use_cases.lock_push import (
        _claimed_slots,
        _unconfirmed_attempts,
        decrypt_pin_or_none,
        unresolved_clear_failures,
    )

    if unresolved_clear_failures(door_code=door_code):
        return True
    attempts = _unconfirmed_attempts(
        door_code=door_code,
        lock_entity_id=lock_entity_id,
        claimed_slots=_claimed_slots(lock_entity_id=lock_entity_id, door_code=door_code),
    )
    if not attempts:
        return False
    pin = decrypt_pin_or_none(door_code)
    return any(attempted_pin or pin for attempted_pin in attempts.values())


def _slots_with_outstanding_cleanup(*, lock_entity_id: str) -> dict[int, list[tuple[int, str | None]]]:
    """Slots on this lock that a code still has a clear or unconfirmed push on record for.

    Maps slot -> [(door code id, PIN the slot is expected to hold)]. The PIN is
    the one stored with the marker, or the code's current PIN for markers from
    before it was stored, and ``None`` when neither can be read.
    """
    from locks.use_cases.lock_push import (
        _CLEAR_FAILED_ACTION,
        _UNCONFIRMED_PUSH_ACTION,
        _unconfirmed_attempts,
        decrypt_pin_or_none,
        unresolved_clear_failures,
    )

    code_ids = (
        DoorCodeEvent.objects.filter(
            lock_entity_id=lock_entity_id,
            door_code__isnull=False,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata__action__in=[_CLEAR_FAILED_ACTION, _UNCONFIRMED_PUSH_ACTION],
        )
        .values_list("door_code_id", flat=True)
        .distinct()
    )
    slots: dict[int, list[tuple[int, str | None]]] = {}
    for door_code in DoorCode.objects.filter(id__in=list(code_ids)).order_by("id"):
        current_pin = decrypt_pin_or_none(door_code)
        for failure in unresolved_clear_failures(door_code=door_code):
            if failure.lock_entity_id == lock_entity_id:
                slots.setdefault(int(failure.slot_index), []).append(
                    (door_code.id, failure.expected_pin or current_pin)
                )
        for slot_index, expected_pin in _unconfirmed_attempts(
            door_code=door_code, lock_entity_id=lock_entity_id
        ).items():
            slots.setdefault(int(slot_index), []).append((door_code.id, expected_pin or current_pin))
    return slots


def _outstanding_cleanup_owner(*, markers: list[tuple[int, str | None]], raw_pin: str | None) -> int | None:
    """The code whose outstanding clear or unconfirmed push this untracked slot may still be (issue #150).

    The sync doesn't import such a slot, since that code's own retry reads it
    back and clears it. That's when the slot holds the PIN the marker expects,
    or a PIN the sync can't read. A readable PIN no marker expects is someone
    else's code (one entered on the keypad, say) and is imported as usual, and
    so is a slot whose markers have no PIN to compare, since the cleanup skips
    those too and would never settle them (#167).
    """
    for door_code_id, expected_pin in markers:
        if expected_pin is not None and (raw_pin is None or raw_pin == expected_pin):
            return door_code_id
    return None


def _assigned_code_pins(*, lock_entity_id: str) -> list[tuple[int, int | None, str]]:
    """(door code id, tracked slot or None, PIN) for every code assigned to this lock with a readable PIN."""
    from locks.use_cases.lock_push import decrypt_pin_or_none

    pins: list[tuple[int, int | None, str]] = []
    assignments = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(lock_entity_id=lock_entity_id, door_code__encrypted_pin__isnull=False)
        .order_by("door_code_id")
    )
    for assignment in assignments:
        pin = decrypt_pin_or_none(assignment.door_code)
        if pin:
            pins.append((assignment.door_code_id, assignment.slot_index, pin))
    return pins


def _flag_duplicate_pins(
    *,
    lock_entity_id: str,
    pin_by_slot: dict[int, str | None],
    slot_results: dict[int, SlotSyncResult],
    slot_events: dict[int, DoorCodeEvent],
) -> None:
    """Flag slots holding the PIN of another code on this lock outside that code's tracked slot (issue #140).

    Catches copies stranded before #136 (#133), including ones an older sync
    already imported as a synced "Slot N": the original and the copy each get
    flagged with the other's id on every sync. Runs once the sync has written its
    changes, so it compares against the PINs codes have now, and leaves out the
    code tracked in the slot itself. 2 codes that share a PIN on purpose get
    flagged too. Only flagged; the sync never clears a slot.
    """
    assigned_pins = _assigned_code_pins(lock_entity_id=lock_entity_id)
    owner_by_slot: dict[int, int] = dict(
        DoorCodeLockAssignment.objects.filter(lock_entity_id=lock_entity_id, slot_index__isnull=False).values_list(
            "slot_index", "door_code_id"
        )
    )
    for slot_index, row in sorted(slot_results.items()):
        pin = pin_by_slot.get(slot_index)
        if pin is None:
            continue
        owner_id = owner_by_slot.get(slot_index)
        duplicate_ids = sorted(
            {
                door_code_id
                for door_code_id, tracked, code_pin in assigned_pins
                if code_pin == pin and tracked != slot_index and door_code_id != owner_id
            }
        )
        if not duplicate_ids:
            continue
        logger.warning(
            "Slot %d on %s holds the PIN of door code(s) %s, which don't track that slot",
            slot_index,
            lock_entity_id,
            duplicate_ids,
        )
        row.warnings.append(_WARN_DUPLICATE_PIN)
        row.duplicate_pin_door_code_ids = duplicate_ids
        event = slot_events.get(slot_index)
        if event is not None:
            event.metadata = {**event.metadata, "duplicate_pin_door_code_ids": duplicate_ids}
            event.save(update_fields=["metadata"])


def _existing_code_skip_reason(
    *, code: DoorCode, lock_entity_id: str, raw_pin: str | None, latchpoint_slot: bool = False
) -> str | None:
    """Why the sync must leave the code tracked in this slot alone, or ``None`` to reconcile it (issue #150).

    - any code with a clear or unconfirmed push still outstanding: its slot may
      hold an older PIN and taking ``is_active`` from the lock could switch on a
      code #144 turned off
    - a manual code that's off: latchpoint turned it off, so the PIN still in its
      slot is a clear that hasn't happened, not the lock's say
    - a manual code whose slot holds a different PIN: flagged, never adopted.
      The same goes for a synced code's slot latchpoint pushed itself
      (``latchpoint_slot``, ADR 0082), since that slot isn't where its PIN comes
      from. A synced code that's off keeps such a slot without a skip, since no
      clear is coming for it
    - any code whose schedule latchpoint still owes this lock (``schedule_pending``,
      issue #123): the lock has the PIN without its schedule, so taking the
      schedule (or none) from the lock and marking it pushed would drop the
      resend and leave the PIN working around the clock. The scheduler sends the
      schedule, and the next sync reconciles it
    """
    if _has_outstanding_slot_cleanup(door_code=code, lock_entity_id=lock_entity_id):
        return _SKIP_CLEAR_OUTSTANDING
    if DoorCodeLockAssignment.objects.filter(
        door_code=code, lock_entity_id=lock_entity_id, schedule_pending=True
    ).exists():
        return _SKIP_SCHEDULE_PENDING
    synced = code.source == DoorCode.Source.SYNCED
    if synced and not latchpoint_slot:
        return None
    if not synced and not code.is_active:
        return _SKIP_INACTIVE_MANUAL_CODE
    if raw_pin is not None:
        from locks.use_cases.lock_push import decrypt_pin_or_none

        if decrypt_pin_or_none(code) != raw_pin:
            return _SKIP_PIN_MISMATCH
    return None


def _apply_slot_pin(*, code: DoorCode, raw_pin: str | None) -> list[str]:
    """Take a PIN read off the code's slot onto ``code``; returns the fields changed.

    Only a readable PIN that differs replaces the stored one. A masked or
    unreadable read says nothing about the PIN, so the stored PIN and
    ``pin_length`` stay (issue #150).
    """
    if raw_pin is None:
        return []
    from locks.use_cases.lock_push import decrypt_pin_or_none

    fields: list[str] = []
    if decrypt_pin_or_none(code) != raw_pin:
        code.encrypted_pin = SettingsEncryption.get().encrypt(raw_pin)
        fields.append("encrypted_pin")
    if code.pin_length != len(raw_pin):
        code.pin_length = len(raw_pin)
        fields.append("pin_length")
    return fields


def _tracked_slot_reads_back_empty(*, zwavejs: ZwavejsGateway, node_id: int, slot_index: int) -> bool:
    """Whether a live CC 99 ``get`` of a tracked slot answers Available twice (issue #166).

    The sync's status read comes from the Z-Wave JS value cache, which can say
    Available while the slot holds a PIN (#194), so the cache alone never lets
    a manual code go. ``userIdStatus`` isn't masked, so a lock that hides its
    codes still answers Occupied for a slot holding one. Read only. ``False``
    for anything else: occupied, empty once then no answer, no answer, out of
    the sync's readback budget or an error.
    """
    from locks.use_cases.lock_push import LockRejectedCode, _out_of_budget, _verify_user_code_slot

    if _out_of_budget(zwavejs):
        return False
    try:
        # Only an empty answer matters, so there's no PIN to compare against.
        _verify_user_code_slot(zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, pin="", timeout_seconds=5.0)
    except LockRejectedCode as exc:
        return bool(exc.clear_slot and not exc.holds_pin)
    except Exception:
        logger.warning("Couldn't read back tracked slot %d on node %d", slot_index, node_id, exc_info=True)
    return False


def _slot_reads_back_disabled(*, zwavejs: ZwavejsGateway, node_id: int, slot_index: int) -> bool:
    """Whether two live CC 99 ``get``\\s of the slot both report a user code that's disabled (issue #221).

    The cache's Occupied/Disabled can be stale the same way its Available can,
    so it's asked twice, like an empty slot is (:func:`_tracked_slot_reads_back_empty`).
    Read only. ``False`` for anything else: enabled, empty, lock config, no
    answer, out of the sync's readback budget or an error.
    """
    from locks.use_cases.lock_push import _out_of_budget, _refresh_user_code_slot

    for _ in range(2):
        if _out_of_budget(zwavejs):
            return False
        try:
            response = _refresh_user_code_slot(
                zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, timeout_seconds=5.0
            )
        except Exception:
            logger.warning("Couldn't read back slot %d on node %d", slot_index, node_id, exc_info=True)
            return False
        if isinstance(response, dict) and "response" in response:
            response = response["response"]
        status = response.get("userIdStatus") if isinstance(response, dict) else None
        if _parse_user_code_status(status) != (True, False):
            return False
    return True


def _off_needs_confirming(*, code: DoorCode, lock_entity_id: str) -> bool:
    """Whether ``code``'s empty or disabled slot on the lock it was imported from needs a live check (issue #221).

    That's a synced code on other locks too, since turning it off takes its PIN
    off them: one that's on, or one that's off and may still have its PIN on one
    of them (a slot it tracks there, or an unconfirmed push). A lock it's being
    dropped from is its clear's.
    """
    from locks.use_cases.lock_push import _locks_being_removed, unconfirmed_attempt_lock_entity_ids

    others = _other_lock_assignments(code=code, lock_entity_id=lock_entity_id).exclude(
        lock_entity_id__in=_locks_being_removed(door_code=code)
    )
    if code.is_active:
        return others.exists()
    if others.filter(slot_index__isnull=False).exists():
        return True
    pending = set(unconfirmed_attempt_lock_entity_ids(door_code=code))
    return any(lock in pending for lock in others.values_list("lock_entity_id", flat=True))


def _import_off_verdicts(
    *,
    lock_entity_id: str,
    node_id: int,
    empty_slots: set[int],
    disabled_slots: set[int],
    pin_by_slot: dict[int, str | None],
    zwavejs: ZwavejsGateway,
) -> dict[int, bool]:
    """Confirm the slots here that would turn a synced code off, when that takes its PIN off other locks (issue #221).

    For a synced code's slot on the lock it was imported from that the cache
    calls Available (``empty_slots``) or Occupied/Disabled (``disabled_slots``),
    when :func:`_off_needs_confirming`. The code going off there takes its PIN
    off the locks someone added to it, and the cache can be stale, so a live
    readback has to give the same twice first: Available twice
    (:func:`_tracked_slot_reads_back_empty`), or disabled twice
    (:func:`_slot_reads_back_disabled`). Maps slot -> whether it did. A slot not
    in the map keeps the old rule. Read only, and run before the sync writes
    anything, like :func:`_empty_manual_slot_verdicts`. Slots the sync skips
    anyway aren't read.
    """
    from locks.use_cases.lock_push import slot_pushed_by_latchpoint

    verdicts: dict[int, bool] = {}
    assignments = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(
            lock_entity_id=lock_entity_id,
            slot_index__in=sorted(empty_slots | disabled_slots),
            door_code__source=DoorCode.Source.SYNCED,
        )
        .order_by("slot_index")
    )
    for assignment in assignments:
        code = assignment.door_code
        slot_index = int(assignment.slot_index)
        if slot_pushed_by_latchpoint(assignment) or not _off_needs_confirming(code=code, lock_entity_id=lock_entity_id):
            continue
        if slot_index in empty_slots:
            if _has_outstanding_slot_cleanup(door_code=code, lock_entity_id=lock_entity_id):
                continue
            verdicts[slot_index] = _tracked_slot_reads_back_empty(
                zwavejs=zwavejs, node_id=node_id, slot_index=slot_index
            )
        else:
            if _existing_code_skip_reason(
                code=code, lock_entity_id=lock_entity_id, raw_pin=pin_by_slot.get(slot_index)
            ):
                continue
            verdicts[slot_index] = _slot_reads_back_disabled(zwavejs=zwavejs, node_id=node_id, slot_index=slot_index)
    return verdicts


def _take_off_other_locks(*, code: DoorCode, lock_entity_id: str) -> list[str]:
    """Flag ``code``'s other locks so the reconcile takes its PIN off them, once the off here is confirmed (issue #221).

    Only the ones that may hold it: a slot the code tracks there or an
    unconfirmed push. One with neither, say a push still queued or a lock
    failed because another code has the PIN there (#188), is left as it is.
    The sync holds only this lock, so it sends nothing to them, like a new PIN
    (:func:`_send_import_change_to_other_locks`). The caller records the
    confirmation on the slot's ``code_synced`` event right after, which is what
    lets the reconcile clear an off code's lock
    (:func:`~locks.use_cases.added_lock_reconcile.off_clear_q`). Returns the locks flagged.
    """
    from locks.use_cases.added_lock_reconcile import OFF_WAITING_ERROR, flag_added_locks
    from locks.use_cases.lock_push import unconfirmed_attempt_lock_entity_ids

    holding = set(
        _other_lock_assignments(code=code, lock_entity_id=lock_entity_id)
        .filter(slot_index__isnull=False)
        .values_list("lock_entity_id", flat=True)
    ) | set(unconfirmed_attempt_lock_entity_ids(door_code=code))
    flagged = flag_added_locks(
        door_code=code,
        import_lock_entity_id=lock_entity_id,
        error=OFF_WAITING_ERROR,
        only=sorted(holding - {lock_entity_id}),
    )
    if flagged:
        logger.info(
            "Door code id=%d is off at %s (confirmed live); taking its PIN off %s", code.id, lock_entity_id, flagged
        )
    return flagged


def _pin_elsewhere_on_lock(
    *, code: DoorCode, lock_entity_id: str, slot_index: int, pin_by_slot: dict[int, str | None]
) -> bool:
    """Whether this lock may already have ``code``'s PIN somewhere other than ``slot_index`` (PR #214 review).

    That's another slot this sync read the PIN in, or another code on this lock
    with the same PIN that holds a slot there or is active and waiting for its
    push, the rule turning a code on uses (#188). Pushing the code again then
    puts a second copy on a lock that keeps duplicates and fails on one that
    drops them. A lock that masks its codes can't be checked against the slots
    it read, only against the other codes.
    """
    from locks.use_cases.lock_push import decrypt_pin_or_none

    pin = decrypt_pin_or_none(code)
    if not pin:
        return False
    if any(other_slot != slot_index and other_pin == pin for other_slot, other_pin in pin_by_slot.items()):
        return True
    others = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(lock_entity_id=lock_entity_id)
        .exclude(door_code=code)
    )
    for assignment in others:
        if assignment.slot_index is None and not assignment.door_code.is_active:
            continue
        if decrypt_pin_or_none(assignment.door_code) == pin:
            return True
    return False


def _empty_manual_slot_verdicts(
    *,
    lock_entity_id: str,
    node_id: int,
    empty_slots: set[int],
    pin_by_slot: dict[int, str | None],
    zwavejs: ZwavejsGateway,
) -> dict[int, str | None]:
    """Decide what happens to each active manual code's tracked slot the cache called Available (issue #166).

    Maps slot -> the reason the code keeps it, or ``None`` to let it go so the
    scheduler pushes the code again (:func:`_release_manual_slot`). Read only,
    and run before the sync writes anything, so no code or assignment row is
    held locked through the Z-Wave readbacks (PR #214 review).

    The cache alone isn't enough (:func:`_tracked_slot_reads_back_empty`), and
    forgetting a slot that still holds the PIN would leave it on the lock with
    nothing tracking it while the push writes a second copy, or fails on a lock
    that drops duplicates. So the slot is only let go when a live readback
    answers Available twice. Before that, a code with a clear or unconfirmed
    push outstanding is left to that cleanup like every other skip, and one
    whose PIN this lock may already have in another slot keeps its slot, since
    pushing it again would add a copy or fail (:func:`_pin_elsewhere_on_lock`).
    Neither of those reads anything back. Inactive manual codes are the #167
    scheduler's to clear or forget.

    A synced code's slot that latchpoint pushed itself, ie on a lock someone
    added to the code (ADR 0082, :func:`~locks.use_cases.lock_push.slot_pushed_by_latchpoint`),
    gets the same treatment, so a stale cache never turns the code off or
    forgets a slot that still holds its PIN. A synced code's slot on the lock
    it was imported from is the lock's, and keeps the synced rule below.
    """
    verdicts: dict[int, str | None] = {}
    assignments = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(
            lock_entity_id=lock_entity_id,
            slot_index__in=sorted(empty_slots),
            door_code__is_active=True,
            # One waiting to be brought in line is the reconcile's (issue #220).
            reconcile_requested_at__isnull=True,
        )
        .exclude(door_code__source=DoorCode.Source.SYNCED, last_push_attempt_at__isnull=True)
        .order_by("slot_index")
    )
    for assignment in assignments:
        code = assignment.door_code
        slot_index = int(assignment.slot_index)
        if _has_outstanding_slot_cleanup(door_code=code, lock_entity_id=lock_entity_id):
            verdicts[slot_index] = _SKIP_CLEAR_OUTSTANDING
        elif _pin_elsewhere_on_lock(
            code=code, lock_entity_id=lock_entity_id, slot_index=slot_index, pin_by_slot=pin_by_slot
        ):
            verdicts[slot_index] = _SKIP_PIN_IN_ANOTHER_SLOT
        elif _tracked_slot_reads_back_empty(zwavejs=zwavejs, node_id=node_id, slot_index=slot_index):
            verdicts[slot_index] = None
        else:
            verdicts[slot_index] = _SKIP_SLOT_NOT_CONFIRMED_EMPTY
    return verdicts


def _release_manual_slot(
    *, code: DoorCode, assignment: DoorCodeLockAssignment, lock_entity_id: str, actor_user: User
) -> None:
    """Let go of the slot :func:`_empty_manual_slot_verdicts` found empty, so the scheduler pushes the code again.

    The slot gets a ``slot_empty`` marker first, so a masked code there later
    isn't counted as another code's older tagged attempt (#193), then a
    ``code_synced`` ``slot_released`` event after it, so this code's own
    re-push into the same slot is tagged like any push into an Available slot.
    The lock goes ``pending`` with no slot and a fresh attempt count, which is
    what the scheduler's push arm picks up.
    """
    from locks.use_cases.lock_push import _settle_unconfirmed_slot

    slot_index = int(assignment.slot_index)
    logger.info(
        "Slot %d on %s (%s code_id=%d) reads back empty: releasing it to push the code again",
        slot_index,
        lock_entity_id,
        code.source,
        code.id,
    )
    # The code row before its assignment row, like every writer of both.
    DoorCode.objects.select_for_update().filter(id=code.id).first()
    _settle_unconfirmed_slot(
        door_code=code, lock_entity_id=lock_entity_id, slot_index=slot_index, outcome="not_holding_pin", slot_empty=True
    )
    assignment.slot_index = None
    assignment.push_state = DoorCode.PushState.PENDING
    assignment.schedule_pending = False
    assignment.push_attempt_count = 0
    assignment.last_push_error = f"Slot {slot_index} read back empty during a lock sync."
    assignment.save(
        update_fields=[
            "slot_index",
            "push_state",
            "schedule_pending",
            "push_attempt_count",
            "last_push_error",
            "updated_at",
        ]
    )
    DoorCodeEvent.objects.create(
        door_code=code,
        user=actor_user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_SYNCED,
        metadata={"slot_index": slot_index, "action": "slot_released", "reason": _WARN_SLOT_EMPTY_REPUSH},
    )


def _other_lock_assignments(*, code: DoorCode, lock_entity_id: str):
    """``code``'s assignments on locks other than ``lock_entity_id``, by lock."""
    return (
        DoorCodeLockAssignment.objects.filter(door_code=code)
        .exclude(lock_entity_id=lock_entity_id)
        .order_by("lock_entity_id")
    )


def _schedule_from_lock(schedule_obj: dict[str, Any] | None) -> tuple[int | None, time | None, time | None]:
    """``(days_of_week, window_start, window_end)`` a slot's schedule read gives a synced code."""
    if schedule_obj is None:
        return None, None, None
    return (
        int(schedule_obj["days_of_week"]),
        time.fromisoformat(str(schedule_obj["window_start"])),
        time.fromisoformat(str(schedule_obj["window_end"])),
    )


def _code_schedule(code: DoorCode) -> tuple[int | None, time | None, time | None]:
    return code.days_of_week, code.window_start, code.window_end


def _import_pin_confirmed(*, zwavejs: ZwavejsGateway, node_id: int, slot_index: int, new_pin: str) -> bool:
    """Whether a live CC 99 ``get`` of the slot reports ``new_pin``, enabled or disabled (issue #220)."""
    from locks.use_cases.lock_push import LockRejectedCode, _out_of_budget, _verify_user_code_slot

    if _out_of_budget(zwavejs):
        return False
    try:
        return _verify_user_code_slot(
            zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, pin=new_pin, timeout_seconds=5.0
        )
    except LockRejectedCode as exc:
        # Disabled at the lock, but it's the new PIN.
        return bool(exc.holds_pin)
    except Exception:
        logger.warning("Couldn't read back slot %d on node %d", slot_index, node_id, exc_info=True)
    return False


def _import_schedule_confirmed(
    *, zwavejs: ZwavejsGateway, node_id: int, slot_index: int, expected: tuple[int | None, time | None, time | None]
) -> bool:
    """Whether a live CC 78 read of the slot's daily repeating entries gives ``expected`` (issue #220).

    Every entry of the slot is read, so a day that was dropped or a schedule
    that went away is seen too. A failed read, an unsupported answer or a sync
    out of its readback budget is ``False``.
    """
    from locks.use_cases.lock_push import _out_of_budget

    if _out_of_budget(zwavejs):
        return False
    try:
        live, unsupported = _extract_daily_repeating_schedule_windows_via_cc_api(
            zwavejs=zwavejs, node_id=node_id, slot_indices={slot_index}, timeout_seconds=5.0
        )
    except Exception:
        logger.warning("Couldn't read back the schedule of slot %d on node %d", slot_index, node_id, exc_info=True)
        return False
    if slot_index in unsupported:
        return False
    return _schedule_from_lock(live.get(slot_index)) == expected


def _import_changes_confirmed(
    *,
    lock_entity_id: str,
    node_id: int,
    occupied_slots: set[int],
    pin_by_slot: dict[int, str | None],
    schedule_by_slot: dict[int, dict[str, Any] | None],
    unsupported_schedule_by_slot: dict[int, str],
    schedule_read_live: bool,
    zwavejs: ZwavejsGateway,
) -> dict[int, tuple[bool, bool]]:
    """Confirm what this sync would take from each slot here of a synced code that's on other locks too (issue #220).

    That's the slot on the lock the code was imported from, whose PIN and
    schedule lock sync takes as the code's and then sends on to its other
    locks, clearing the old ones there (:func:`_send_import_change_to_other_locks`).
    A value read off the Z-Wave JS cache alone may be stale, or one cached for a
    ``set`` the lock dropped, and sending it on would take what works off the
    other locks. So a new PIN is only taken when a live CC 99 ``get`` of the
    slot reports it, and a new schedule (one removed included) when a live CC 78
    read of the slot gives it, unless the sync's schedule read was live already.
    Maps slot -> ``(pin_ok, schedule_ok)``, ``True`` for what didn't change. A
    masked answer, another value, no answer or a sync out of its readback budget
    is ``False``. Read only, and run before the sync writes anything, like
    :func:`_empty_manual_slot_verdicts`. Slots the sync skips anyway aren't read.
    """
    from locks.use_cases.lock_push import decrypt_pin_or_none, slot_pushed_by_latchpoint

    verdicts: dict[int, tuple[bool, bool]] = {}
    assignments = (
        DoorCodeLockAssignment.objects.select_related("door_code")
        .filter(
            lock_entity_id=lock_entity_id,
            slot_index__in=sorted(occupied_slots),
            door_code__source=DoorCode.Source.SYNCED,
        )
        .order_by("slot_index")
    )
    for assignment in assignments:
        code = assignment.door_code
        slot_index = int(assignment.slot_index)
        new_pin = pin_by_slot.get(slot_index)
        if slot_pushed_by_latchpoint(assignment):
            continue
        if not _other_lock_assignments(code=code, lock_entity_id=lock_entity_id).exists():
            continue
        if _existing_code_skip_reason(code=code, lock_entity_id=lock_entity_id, raw_pin=new_pin):
            continue
        pin_ok = new_pin is None or decrypt_pin_or_none(code) == new_pin
        if not pin_ok:
            pin_ok = _import_pin_confirmed(zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, new_pin=new_pin)
        expected = _schedule_from_lock(schedule_by_slot.get(slot_index))
        schedule_ok = (
            slot_index in unsupported_schedule_by_slot or schedule_read_live or _code_schedule(code) == expected
        )
        if not schedule_ok:
            schedule_ok = _import_schedule_confirmed(
                zwavejs=zwavejs, node_id=node_id, slot_index=slot_index, expected=expected
            )
        verdicts[slot_index] = (pin_ok, schedule_ok)
    return verdicts


def _send_import_change_to_other_locks(
    *, code: DoorCode, lock_entity_id: str, pin_changed: bool
) -> tuple[list[str], list[str]]:
    """Flag the code's other locks for a new PIN or schedule lock sync just took from ``lock_entity_id`` (issue #220).

    ``code`` is a synced code and ``lock_entity_id`` the lock it was imported
    from, which decides its PIN and schedule (ADR 0082). Its other locks are
    ones someone added in latchpoint and got the PIN from a push. The sync holds
    only this lock's ``lock_sync:`` lock, so it sends nothing to them. It flags
    them (:func:`~locks.use_cases.added_lock_reconcile.flag_added_locks`) and the
    queued push task brings each in line once this commits
    (:func:`~locks.use_cases.added_lock_reconcile.reconcile_added_lock`).
    Returns the locks flagged, without the ones where another code already has
    the new PIN, which are returned second: the reconcile takes the old PIN
    off those and fails them for a human (the #188 rule).
    """
    from locks.use_cases.added_lock_reconcile import flag_added_locks, pin_held_by_another_code

    flagged = flag_added_locks(door_code=code, import_lock_entity_id=lock_entity_id)
    held = [
        other
        for other in flagged
        if pin_changed and pin_held_by_another_code(door_code=code, lock_entity_id=other) is not None
    ]
    if held:
        logger.warning(
            "Door code id=%d: the new PIN from %s is already another code's on %s; only the old one comes off there",
            code.id,
            lock_entity_id,
            held,
        )
    return [lock for lock in flagged if lock not in held], held


def _record_sync_skip(
    *, code: DoorCode, actor_user: User, lock_entity_id: str, slot_index: int, reason: str, pin_known: bool
) -> DoorCodeEvent:
    return DoorCodeEvent.objects.create(
        door_code=code,
        user=actor_user,
        lock_entity_id=lock_entity_id,
        event_type=DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "action": _SYNC_SKIPPED_ACTION,
            "slot_index": int(slot_index),
            "reason": reason,
            "pin_known": pin_known,
        },
    )


def sync_lock_config(
    *,
    lock_entity_id: str,
    target_user: User,
    actor_user: User,
    zwavejs: ZwavejsGateway,
    dry_run: bool = False,
) -> SyncResult:
    """
    Pull user codes (CC 99) and supported weekday schedules (CC 76) from Z-Wave JS into DoorCode rows.

    Z-Wave JS is authoritative for synced codes. Raw PINs are never returned or persisted.

    The ``lock_sync:`` lock is released only after the sync's transaction has
    committed, so the next push on this lock reads the synced assignments
    (issue #131). Called inside an outer transaction (the dry-run view), the
    sync's block is a savepoint and the lock goes when it's released.
    """
    node_id = _resolve_lock_node_id(lock_entity_id=lock_entity_id)
    logger.info("Starting lock config sync for %s (node %d)", lock_entity_id, node_id)

    # Shared key with the push path (ADR 0092) so push and pull serialize against
    # each other on the same physical lock.
    lock_key = f"lock_sync:{lock_entity_id}"
    acquired, lock_id = _try_acquire_sync_lock(lock_key=lock_key)
    if not acquired:
        logger.info("Sync already in progress for %s, rejecting", lock_entity_id)
        raise SyncInProgress("A sync is already in progress for this lock.")

    try:
        return _sync_lock_config_atomically(
            lock_entity_id=lock_entity_id,
            node_id=node_id,
            target_user=target_user,
            actor_user=actor_user,
            zwavejs=zwavejs,
            dry_run=dry_run,
        )
    finally:
        _release_sync_lock(lock_key=lock_key, lock_id=lock_id)


def _sync_lock_config_atomically(
    *,
    lock_entity_id: str,
    node_id: int,
    target_user: User,
    actor_user: User,
    zwavejs: ZwavejsGateway,
    dry_run: bool,
) -> SyncResult:
    """The body of :func:`sync_lock_config`, run in one transaction while the caller holds the lock."""
    result = SyncResult(lock_entity_id=lock_entity_id, node_id=node_id, slots=[])
    # Codes whose row or assignment the sync changed; their rollup is refreshed at the end (issue #126).
    touched_code_ids: set[int] = set()
    with transaction.atomic():
        value_ids = zwavejs.node_get_defined_value_ids(node_id=node_id, timeout_seconds=10.0)
        if not isinstance(value_ids, list):
            value_ids = []

        cc99 = [vid for vid in value_ids if isinstance(vid, dict) and vid.get("commandClass") == CC_USER_CODE]
        if not cc99:
            logger.warning("Lock %s (node %d) does not expose CC 99 value IDs", lock_entity_id, node_id)
            raise InvalidRequest("Lock does not expose User Code (CC 99) value IDs.")

        users_number_vid = next(
            (vid for vid in cc99 if isinstance(vid.get("property"), str) and vid.get("property") == "usersNumber"),
            None,
        )
        max_slots = None
        if users_number_vid is not None:
            try:
                max_slots = _coerce_int(
                    zwavejs.node_get_value(node_id=node_id, value_id=users_number_vid, timeout_seconds=10.0)
                )
            except Exception:
                max_slots = None
        if not isinstance(max_slots, int) or max_slots <= 0:
            # Fallback: infer from value IDs (status/code propertyKey).
            keys: set[int] = set()
            for vid in cc99:
                if vid.get("property") not in {"userIdStatus", "userCode"}:
                    continue
                keys_int = _coerce_int(vid.get("propertyKey"))
                if isinstance(keys_int, int) and keys_int >= 0:
                    keys.add(int(keys_int))
            if keys:
                max_slots = max(keys)

        if not isinstance(max_slots, int) or max_slots <= 0:
            logger.warning("Cannot determine slot count for %s (node %d)", lock_entity_id, node_id)
            raise InvalidRequest("Unable to determine lock user-code slot count.")

        logger.info("Lock %s (node %d): max_slots=%d", lock_entity_id, node_id, max_slots)

        status_vid_by_slot: dict[int, dict[str, Any]] = {}
        code_vid_by_slot: dict[int, dict[str, Any]] = {}
        for vid in cc99:
            prop = vid.get("property")
            if prop not in {"userIdStatus", "userCode"}:
                continue
            slot = _coerce_int(vid.get("propertyKey"))
            if not isinstance(slot, int) or slot < 0:
                continue
            if prop == "userIdStatus":
                status_vid_by_slot[int(slot)] = vid
            if prop == "userCode":
                code_vid_by_slot[int(slot)] = vid

        occupied_slots: set[int] = set()
        # Slots whose status read worked and said Available. Only these turn a
        # synced code off; a failed or inconclusive read says nothing (issue #149).
        confirmed_empty_slots: set[int] = set()
        slot_active: dict[int, bool | None] = {}
        pin_known_by_slot: dict[int, bool] = {}
        pin_by_slot: dict[int, str | None] = {}
        pin_length_by_slot: dict[int, int | None] = {}

        for slot_index in range(1, int(max_slots) + 1):
            status_vid = status_vid_by_slot.get(slot_index) or {
                "commandClass": CC_USER_CODE,
                "property": "userIdStatus",
                "propertyKey": slot_index,
            }
            try:
                status_value = zwavejs.node_get_value(node_id=node_id, value_id=status_vid, timeout_seconds=10.0)
            except Exception as exc:
                logger.warning("Failed to read slot %d status on node %d: %s", slot_index, node_id, exc)
                result.errors += 1
                result.slots.append(
                    SlotSyncResult(
                        slot_index=slot_index,
                        action="error",
                        error=f"Failed to read slot status: {exc.__class__.__name__}",
                    )
                )
                continue

            is_occupied, is_active = _parse_user_code_status(status_value)
            if not is_occupied:
                if _is_confirmed_empty_status(status_value):
                    confirmed_empty_slots.add(slot_index)
                continue

            occupied_slots.add(slot_index)
            slot_active[slot_index] = is_active

            code_vid = code_vid_by_slot.get(slot_index) or {
                "commandClass": CC_USER_CODE,
                "property": "userCode",
                "propertyKey": slot_index,
            }
            try:
                code_value = zwavejs.node_get_value(node_id=node_id, value_id=code_vid, timeout_seconds=10.0)
            except Exception:
                code_value = None

            known, pin = _normalize_pin(code_value)
            pin_known_by_slot[slot_index] = bool(known)
            pin_by_slot[slot_index] = pin if known else None
            pin_length_by_slot[slot_index] = len(pin) if known and pin is not None else None

        logger.info(
            "Lock %s (node %d): %d occupied slots out of %d",
            lock_entity_id,
            node_id,
            len(occupied_slots),
            max_slots,
        )

        schedule_by_slot, unsupported_schedule_by_slot = _extract_weekday_schedule_windows(
            zwavejs=zwavejs,
            node_id=node_id,
            value_ids=value_ids,
            slot_indices=set(occupied_slots),
            timeout_seconds=10.0,
        )

        # An untracked slot the cache says is Available doesn't disprove an
        # unconfirmed attempt there on its own, so those slots are read back
        # live, and an empty one gets its slot_empty marker (issue #194). All
        # of them share one budget, since this is the request and the sync's
        # transaction, and a dry run doesn't read anything back (PR #211 review).
        # The tracked slots of active manual codes share that budget and are read
        # first, before the sync writes or locks any row (issue #166, PR #214 review).
        manual_empty_verdicts: dict[int, str | None] = {}
        # (pin_ok, schedule_ok) for each slot of a synced code that's on other
        # locks too, from live readbacks of what changed (issue #220).
        import_verdicts: dict[int, tuple[bool, bool]] = {}
        # Whether each import lock slot that would turn a synced code on other
        # locks off was confirmed empty or disabled live (issue #221).
        off_verdicts: dict[int, bool] = {}
        if not dry_run:
            from locks.use_cases.lock_push import (
                SYNC_READBACK_BUDGET_SECONDS,
                BudgetedGateway,
                check_attempt_slots_sync_saw_empty,
            )

            readback_gateway = BudgetedGateway(zwavejs, seconds=SYNC_READBACK_BUDGET_SECONDS)
            manual_empty_verdicts = _empty_manual_slot_verdicts(
                lock_entity_id=lock_entity_id,
                node_id=node_id,
                empty_slots=confirmed_empty_slots,
                pin_by_slot=pin_by_slot,
                zwavejs=readback_gateway,
            )
            import_verdicts = _import_changes_confirmed(
                lock_entity_id=lock_entity_id,
                node_id=node_id,
                occupied_slots=occupied_slots,
                pin_by_slot=pin_by_slot,
                schedule_by_slot=schedule_by_slot,
                unsupported_schedule_by_slot=unsupported_schedule_by_slot,
                # The cache-less fallback of _extract_weekday_schedule_windows reads the lock live.
                schedule_read_live=not any(
                    isinstance(vid, dict) and vid.get("commandClass") == CC_SCHEDULE_ENTRY_LOCK for vid in value_ids
                ),
                zwavejs=readback_gateway,
            )
            off_verdicts = _import_off_verdicts(
                lock_entity_id=lock_entity_id,
                node_id=node_id,
                empty_slots=confirmed_empty_slots,
                disabled_slots={slot for slot in occupied_slots if slot_active.get(slot) is False},
                pin_by_slot=pin_by_slot,
                zwavejs=readback_gateway,
            )
            tracked_slots = set(
                DoorCodeLockAssignment.objects.filter(
                    lock_entity_id=lock_entity_id, slot_index__isnull=False
                ).values_list("slot_index", flat=True)
            )
            touched_code_ids.update(
                check_attempt_slots_sync_saw_empty(
                    lock_entity_id=lock_entity_id,
                    node_id=node_id,
                    empty_slots=confirmed_empty_slots - tracked_slots,
                    zwavejs=readback_gateway,
                )
            )

        # Read before anything below changes the assignments.
        outstanding_cleanup_by_slot = _slots_with_outstanding_cleanup(lock_entity_id=lock_entity_id)
        # Rows and events per slot, for the duplicate PIN flags added at the end.
        slot_results: dict[int, SlotSyncResult] = {}
        slot_events: dict[int, DoorCodeEvent] = {}

        def add_slot_result(row: SlotSyncResult, event: DoorCodeEvent | None = None) -> None:
            result.slots.append(row)
            slot_results[row.slot_index] = row
            if event is not None:
                slot_events[row.slot_index] = event

        def skip_slot(
            *, code: DoorCode, slot_index: int, reason: str, pin_known: bool | None, is_active, warnings: list[str]
        ) -> None:
            logger.warning("Slot %d on %s: skipped (%s, code_id=%d)", slot_index, lock_entity_id, reason, code.id)
            event = _record_sync_skip(
                code=code,
                actor_user=actor_user,
                lock_entity_id=lock_entity_id,
                slot_index=slot_index,
                reason=reason,
                pin_known=bool(pin_known),
            )
            result.skipped += 1
            add_slot_result(
                SlotSyncResult(
                    slot_index=slot_index,
                    action="skipped",
                    door_code_id=code.id,
                    pin_known=pin_known,
                    is_active=bool(is_active) if is_active is not None else None,
                    warnings=[*warnings, reason],
                ),
                event,
            )

        from locks.use_cases.added_lock_reconcile import OFF_CONFIRMED_KEY
        from locks.use_cases.lock_push import decrypt_pin_or_none, slot_pushed_by_latchpoint

        # Import occupied slots.
        for slot_index in sorted(occupied_slots):
            existing = (
                DoorCodeLockAssignment.objects.select_related("door_code")
                .filter(lock_entity_id=lock_entity_id, slot_index=slot_index)
                .first()
            )
            pin_known = bool(pin_known_by_slot.get(slot_index))
            is_active = slot_active.get(slot_index)
            raw_pin = pin_by_slot.get(slot_index)
            pin_length = pin_length_by_slot.get(slot_index)

            schedule_obj = schedule_by_slot.get(slot_index)
            schedule_unsupported_reason = unsupported_schedule_by_slot.get(slot_index)

            warnings: list[str] = []
            if schedule_unsupported_reason:
                warnings.append("schedule_unsupported")

            skip_code: DoorCode | None = None
            skip_reason: str | None = None
            # Latchpoint's own slot: a manual code's, or one latchpoint pushed for
            # a synced code on a lock someone added to it (ADR 0082).
            latchpoint_slot = bool(existing) and (
                existing.door_code.source != DoorCode.Source.SYNCED or slot_pushed_by_latchpoint(existing)
            )
            if existing and latchpoint_slot and existing.reconcile_requested_at is not None:
                # A synced code's added lock waiting to be brought in line owns
                # its slot until then (issue #220), whatever the cache says now.
                skip_reason = _SKIP_UPDATE_PENDING
                skip_code = existing.door_code
            elif existing:
                skip_reason = _existing_code_skip_reason(
                    code=existing.door_code,
                    lock_entity_id=lock_entity_id,
                    raw_pin=raw_pin,
                    latchpoint_slot=latchpoint_slot,
                )
                skip_code = existing.door_code if skip_reason else None
            elif slot_index in outstanding_cleanup_by_slot:
                owner_id = _outstanding_cleanup_owner(markers=outstanding_cleanup_by_slot[slot_index], raw_pin=raw_pin)
                if owner_id is not None:
                    skip_reason = _SKIP_CLEAR_OUTSTANDING
                    skip_code = DoorCode.objects.filter(id=owner_id).first()
            if skip_reason and skip_code is not None:
                skip_slot(
                    code=skip_code,
                    slot_index=slot_index,
                    reason=skip_reason,
                    pin_known=pin_known,
                    is_active=is_active,
                    warnings=warnings,
                )
                continue

            if existing and latchpoint_slot:
                # An active manual code whose slot holds its PIN or a masked one
                # (the skips above catch the rest). Latchpoint owns it, so it
                # stays manual and editable, and its PIN, schedule, owner and
                # active flag are left alone (issue #166). Codes an older sync
                # already converted stay synced. A synced code's slot latchpoint
                # pushed to a lock someone added gets the same, on or off: its
                # PIN, schedule, owner and active flag come from the lock it was
                # imported from, so this lock never turns it back on, gives it
                # another PIN or owner (ADR 0082).
                code = existing.door_code
                action = "unchanged"
                disabled_on_lock = is_active is False
                if disabled_on_lock:
                    warnings.append(_WARN_DISABLED_ON_LOCK)
                    # The PIN won't open the door, so the lock's chip says so instead
                    # of a bare "On lock" (PR #214 review). The slot is still the
                    # code's, so the lock is pushed (which the scheduler's repair
                    # leaves alone, error included), and the next sync that finds
                    # the slot enabled clears the error.
                    disabled_error = f"Slot {slot_index} is disabled at the lock."
                    if existing.push_state != DoorCode.PushState.PUSHED or existing.last_push_error != disabled_error:
                        DoorCode.objects.select_for_update().filter(id=code.id).first()
                        DoorCodeLockAssignment.objects.filter(id=existing.id).update(
                            push_state=DoorCode.PushState.PUSHED, push_attempt_count=0, last_push_error=disabled_error
                        )
                        touched_code_ids.add(code.id)
                elif (
                    existing.push_state != DoorCode.PushState.PUSHED
                    or existing.push_attempt_count
                    or existing.last_push_error
                ):
                    # The lock holds it in the slot it tracks, so per lock it's pushed,
                    # like the old conversion did (issue #126). After the code row,
                    # like every writer of both.
                    DoorCode.objects.select_for_update().filter(id=code.id).first()
                    DoorCodeLockAssignment.objects.filter(id=existing.id).update(
                        push_state=DoorCode.PushState.PUSHED, push_attempt_count=0, last_push_error=""
                    )
                    touched_code_ids.add(code.id)
                    action = "updated"
                if action == "updated":
                    result.updated += 1
                else:
                    result.unchanged += 1
                logger.debug("Slot %d on %s: manual code %d matches (%s)", slot_index, lock_entity_id, code.id, action)
                event = DoorCodeEvent.objects.create(
                    door_code=code,
                    user=actor_user,
                    lock_entity_id=lock_entity_id,
                    event_type=DoorCodeEvent.EventType.CODE_SYNCED,
                    metadata={
                        "slot_index": slot_index,
                        "action": action,
                        "pin_known": pin_known,
                        "schedule_applied": False,
                        "schedule_unsupported": bool(schedule_unsupported_reason),
                        **({_WARN_DISABLED_ON_LOCK: True} if disabled_on_lock else {}),
                    },
                )
                add_slot_result(
                    SlotSyncResult(
                        slot_index=slot_index,
                        action=action,
                        door_code_id=code.id,
                        pin_known=pin_known,
                        is_active=bool(is_active) if is_active is not None else None,
                        schedule_unsupported=bool(schedule_unsupported_reason),
                        warnings=warnings,
                    ),
                    event,
                )
                continue

            if existing:
                code = existing.door_code
                updated_fields: list[str] = []
                old_pin = decrypt_pin_or_none(code)

                if code.user_id != target_user.id:
                    code.user = target_user
                    updated_fields.append("user")
                    warnings.append("owner_changed")

                # A code that's on other locks too only takes what a live readback
                # confirmed, since it goes on to those locks (issue #220). A slot
                # the readbacks didn't get to counts as unconfirmed.
                pin_ok, schedule_ok = (
                    import_verdicts.get(slot_index, (False, False))
                    if not dry_run and _other_lock_assignments(code=code, lock_entity_id=lock_entity_id).exists()
                    else (True, True)
                )
                if pin_ok or raw_pin is None or old_pin == raw_pin:
                    updated_fields.extend(_apply_slot_pin(code=code, raw_pin=raw_pin))
                else:
                    warnings.append(_WARN_PIN_CHANGE_UNCONFIRMED)
                # A code on other locks too only goes off here once two live reads
                # confirm the slot disabled, since that takes its PIN off them (issue #221).
                off_verdict = off_verdicts.get(slot_index) if is_active is False else None
                if is_active is not None and code.is_active != bool(is_active):
                    if off_verdict is False:
                        warnings.append(_WARN_OFF_CHANGE_UNCONFIRMED)
                    else:
                        code.is_active = bool(is_active)
                        updated_fields.append("is_active")

                schedule_applied = False
                schedule_unsupported = bool(schedule_unsupported_reason)
                schedule_held = (
                    not schedule_unsupported
                    and not schedule_ok
                    and _code_schedule(code) != _schedule_from_lock(schedule_obj)
                )
                if schedule_held:
                    warnings.append(_WARN_SCHEDULE_CHANGE_UNCONFIRMED)
                elif not schedule_unsupported:
                    if schedule_obj is None:
                        # No schedule => clear weekday window.
                        if code.days_of_week is not None:
                            code.days_of_week = None
                            updated_fields.append("days_of_week")
                        if code.window_start is not None:
                            code.window_start = None
                            updated_fields.append("window_start")
                        if code.window_end is not None:
                            code.window_end = None
                            updated_fields.append("window_end")
                        if code.code_type != DoorCode.CodeType.PERMANENT:
                            code.code_type = DoorCode.CodeType.PERMANENT
                            updated_fields.append("code_type")
                    else:
                        schedule_applied = True
                        days_mask = int(schedule_obj["days_of_week"])
                        start_str = str(schedule_obj["window_start"])
                        end_str = str(schedule_obj["window_end"])
                        start_t = time.fromisoformat(start_str)
                        end_t = time.fromisoformat(end_str)
                        if code.days_of_week != days_mask:
                            code.days_of_week = days_mask
                            updated_fields.append("days_of_week")
                        if code.window_start != start_t:
                            code.window_start = start_t
                            updated_fields.append("window_start")
                        if code.window_end != end_t:
                            code.window_end = end_t
                            updated_fields.append("window_end")
                        if code.code_type != DoorCode.CodeType.TEMPORARY:
                            code.code_type = DoorCode.CodeType.TEMPORARY
                            updated_fields.append("code_type")

                if not code.label:
                    code.label = f"Slot {slot_index}"
                    updated_fields.append("label")

                action = "unchanged"
                if updated_fields:
                    code.save(update_fields=[*set(updated_fields), "updated_at"])
                    touched_code_ids.add(code.id)
                    action = "updated"
                    result.updated += 1
                    logger.info("Slot %d on %s: updated (fields: %s)", slot_index, lock_entity_id, updated_fields)
                else:
                    result.unchanged += 1
                    logger.debug("Slot %d on %s: unchanged", slot_index, lock_entity_id)

                # This is the lock the code was imported from, so a new PIN or
                # schedule goes on to the locks added to it (issue #220).
                sent_to: list[str] = []
                held_on: list[str] = []
                taken_off: list[str] = []
                pin_changed = "encrypted_pin" in updated_fields
                schedule_changed = bool({"days_of_week", "window_start", "window_end"} & set(updated_fields))
                if off_verdict:
                    # Off here, confirmed live: its PIN comes off the other locks
                    # instead, whatever else changed (issue #221). Also for a code
                    # that was already off and may still be on one of them.
                    taken_off = _take_off_other_locks(code=code, lock_entity_id=lock_entity_id)
                    touched_code_ids.add(code.id)
                    if taken_off:
                        warnings.append(_WARN_TAKING_OFF_OTHER_LOCKS)
                elif not dry_run and (pin_changed or schedule_changed):
                    sent_to, held_on = _send_import_change_to_other_locks(
                        code=code, lock_entity_id=lock_entity_id, pin_changed=pin_changed
                    )
                    if sent_to:
                        warnings.append(_WARN_SENT_TO_OTHER_LOCKS)
                    if held_on:
                        warnings.append(_WARN_PIN_HELD_ON_OTHER_LOCK)
                elif not dry_run and "is_active" in updated_fields and code.is_active:
                    # Back on: the added locks it left behind while it was off go
                    # now, not at the scheduler's next 300s retry (review of PR #223).
                    from locks.use_cases.added_lock_reconcile import flag_added_locks, pin_held_by_another_code

                    flagged = flag_added_locks(
                        door_code=code, import_lock_entity_id=lock_entity_id, out_of_date_only=True
                    )
                    # The #188 rule, like a change: the reconcile only clears those.
                    held_on = [
                        other
                        for other in flagged
                        if pin_held_by_another_code(door_code=code, lock_entity_id=other) is not None
                    ]
                    sent_to = [other for other in flagged if other not in held_on]
                    if sent_to:
                        warnings.append(_WARN_SENT_TO_OTHER_LOCKS)
                    if held_on:
                        warnings.append(_WARN_PIN_HELD_ON_OTHER_LOCK)

                event = DoorCodeEvent.objects.create(
                    door_code=code,
                    user=actor_user,
                    lock_entity_id=lock_entity_id,
                    event_type=DoorCodeEvent.EventType.CODE_SYNCED,
                    metadata={
                        "slot_index": slot_index,
                        "action": action,
                        "pin_known": pin_known,
                        "schedule_applied": schedule_applied,
                        "schedule_unsupported": schedule_unsupported,
                        **({"sent_to_lock_entity_ids": sent_to} if sent_to else {}),
                        **({"pin_held_on_lock_entity_ids": held_on} if held_on else {}),
                        **({_WARN_PIN_CHANGE_UNCONFIRMED: True} if _WARN_PIN_CHANGE_UNCONFIRMED in warnings else {}),
                        **({_WARN_SCHEDULE_CHANGE_UNCONFIRMED: True} if schedule_held else {}),
                        **({_WARN_OFF_CHANGE_UNCONFIRMED: True} if _WARN_OFF_CHANGE_UNCONFIRMED in warnings else {}),
                        # After the flags, so the reconcile sees them as set by this (off_clear_q).
                        **({OFF_CONFIRMED_KEY: True, "taken_off_lock_entity_ids": taken_off} if off_verdict else {}),
                    },
                )

                add_slot_result(
                    SlotSyncResult(
                        slot_index=slot_index,
                        action=action,
                        door_code_id=code.id,
                        pin_known=pin_known,
                        is_active=bool(is_active) if is_active is not None else None,
                        schedule_applied=schedule_applied,
                        schedule_unsupported=schedule_unsupported,
                        schedule=schedule_obj,
                        warnings=warnings,
                    ),
                    event,
                )
                continue

            # Create new synced door code + assignment.
            code_type = DoorCode.CodeType.PERMANENT
            schedule_applied = False
            schedule_unsupported = bool(schedule_unsupported_reason)
            days_mask: int | None = None
            window_start: time | None = None
            window_end: time | None = None
            if not schedule_unsupported and schedule_obj is not None:
                schedule_applied = True
                days_mask = int(schedule_obj["days_of_week"])
                window_start = time.fromisoformat(str(schedule_obj["window_start"]))
                window_end = time.fromisoformat(str(schedule_obj["window_end"]))
                code_type = DoorCode.CodeType.TEMPORARY

            enc = SettingsEncryption.get()
            encrypted_pin = enc.encrypt(raw_pin) if raw_pin is not None else None
            code = DoorCode(
                user=target_user,
                source=DoorCode.Source.SYNCED,
                encrypted_pin=encrypted_pin,
                label=f"Slot {slot_index}",
                code_type=code_type,
                pin_length=pin_length,
                is_active=bool(is_active) if is_active is not None else True,
                days_of_week=days_mask,
                window_start=window_start,
                window_end=window_end,
                # It's read off the lock, so it's already there (issue #149).
                push_state=DoorCode.PushState.PUSHED,
            )
            code.save()

            try:
                # A savepoint, so the transaction is still usable for the fallback below.
                with transaction.atomic():
                    DoorCodeLockAssignment.objects.create(
                        door_code=code,
                        lock_entity_id=lock_entity_id,
                        slot_index=slot_index,
                        # Read off the lock like the code's own push_state (issue #126).
                        push_state=DoorCode.PushState.PUSHED,
                    )
            except IntegrityError:
                # Race: another sync created the assignment first. Update the winner's code
                # with our freshly-read data so it isn't silently discarded.
                logger.warning(
                    "IntegrityError on slot %d for lock %s — updating existing assignment",
                    slot_index,
                    lock_entity_id,
                )
                existing = (
                    DoorCodeLockAssignment.objects.select_related("door_code")
                    .filter(lock_entity_id=lock_entity_id, slot_index=slot_index)
                    .first()
                )
                if existing:
                    code.delete()
                    existing_code = existing.door_code
                    race_latchpoint_slot = existing_code.source != DoorCode.Source.SYNCED or slot_pushed_by_latchpoint(
                        existing
                    )
                    # Same guards as a code that already held the slot (issue #150).
                    race_skip_reason = _existing_code_skip_reason(
                        code=existing_code,
                        lock_entity_id=lock_entity_id,
                        raw_pin=raw_pin,
                        latchpoint_slot=race_latchpoint_slot,
                    )
                    if race_skip_reason:
                        skip_slot(
                            code=existing_code,
                            slot_index=slot_index,
                            reason=race_skip_reason,
                            pin_known=pin_known,
                            is_active=is_active,
                            warnings=[*warnings, "integrity_race"],
                        )
                        continue
                    race_fields = _apply_slot_pin(code=existing_code, raw_pin=raw_pin)
                    # A manual code's active flag is latchpoint's, not the lock's
                    # (issue #166), and so is a synced code's on a slot latchpoint pushed.
                    if (
                        not race_latchpoint_slot
                        and is_active is not None
                        and existing_code.is_active != bool(is_active)
                    ):
                        existing_code.is_active = bool(is_active)
                        race_fields.append("is_active")
                    if race_fields:
                        existing_code.save(update_fields=[*race_fields, "updated_at"])
                        touched_code_ids.add(existing_code.id)
                    result.updated += 1
                    add_slot_result(
                        SlotSyncResult(
                            slot_index=slot_index,
                            action="updated",
                            door_code_id=existing.door_code_id,
                            pin_known=pin_known,
                            is_active=bool(is_active) if is_active is not None else None,
                            schedule_applied=schedule_applied,
                            schedule_unsupported=schedule_unsupported,
                            schedule=schedule_obj,
                            warnings=[*warnings, "integrity_race"],
                        )
                    )
                    continue
                raise

            event = DoorCodeEvent.objects.create(
                door_code=code,
                user=actor_user,
                lock_entity_id=lock_entity_id,
                event_type=DoorCodeEvent.EventType.CODE_SYNCED,
                metadata={
                    "slot_index": slot_index,
                    "action": "created",
                    "pin_known": pin_known,
                    "schedule_applied": schedule_applied,
                    "schedule_unsupported": schedule_unsupported,
                },
            )

            result.created += 1
            logger.info(
                "Slot %d on %s: created (code_id=%d, pin_known=%s)", slot_index, lock_entity_id, code.id, pin_known
            )
            add_slot_result(
                SlotSyncResult(
                    slot_index=slot_index,
                    action="created",
                    door_code_id=code.id,
                    pin_known=pin_known,
                    is_active=bool(is_active) if is_active is not None else None,
                    schedule_applied=schedule_applied,
                    schedule_unsupported=schedule_unsupported,
                    schedule=schedule_obj,
                    warnings=warnings,
                ),
                event,
            )

        # Turn off synced codes whose slot read back empty and stop tracking the slot.
        # A slot whose read failed or was inconclusive isn't touched: its PIN may
        # still be on the lock (issue #149). Nor is a code with a clear or unconfirmed
        # push outstanding, since the code_synced event would end its push_unconfirmed
        # window, and its own retry settles the slot.
        previously_synced = DoorCodeLockAssignment.objects.select_related("door_code").filter(
            lock_entity_id=lock_entity_id, slot_index__isnull=False
        )
        for assignment in previously_synced:
            if assignment.slot_index is None:
                continue
            slot_index = int(assignment.slot_index)
            if slot_index <= 0:
                continue
            if slot_index not in confirmed_empty_slots:
                continue
            code = assignment.door_code
            if not code:
                continue
            if code.source != DoorCode.Source.SYNCED or slot_pushed_by_latchpoint(assignment):
                # Only the active ones _empty_manual_slot_verdicts looked at. An
                # inactive manual code is the #167 scheduler's to clear or forget,
                # and a dry run reads nothing back, so it can't tell (PR #211 review).
                # A synced code's slot latchpoint pushed to a lock someone added
                # goes the same way, so it's released and pushed again once it
                # reads back empty and the code is never turned off for it. When
                # the code is off it's left alone, and its next sync once it's on
                # again checks the slot (ADR 0082).
                if code.is_active and slot_index in manual_empty_verdicts:
                    manual_skip_reason = manual_empty_verdicts[slot_index]
                    if manual_skip_reason:
                        skip_slot(
                            code=code,
                            slot_index=slot_index,
                            reason=manual_skip_reason,
                            pin_known=None,
                            is_active=None,
                            warnings=[],
                        )
                    else:
                        _release_manual_slot(
                            code=code, assignment=assignment, lock_entity_id=lock_entity_id, actor_user=actor_user
                        )
                        touched_code_ids.add(code.id)
                        result.updated += 1
                        add_slot_result(
                            SlotSyncResult(
                                slot_index=slot_index,
                                action="updated",
                                door_code_id=code.id,
                                warnings=[_WARN_SLOT_EMPTY_REPUSH],
                            )
                        )
                continue
            if _has_outstanding_slot_cleanup(door_code=code, lock_entity_id=lock_entity_id):
                skip_slot(
                    code=code,
                    slot_index=slot_index,
                    reason=_SKIP_CLEAR_OUTSTANDING,
                    pin_known=None,
                    is_active=None,
                    warnings=[],
                )
                continue
            off_verdict = off_verdicts.get(slot_index)
            if off_verdict is False:
                # On other locks too, and two live reads didn't confirm the slot
                # empty: the code stays as it is with its slot (issue #221).
                skip_slot(
                    code=code,
                    slot_index=slot_index,
                    reason=_SKIP_SLOT_NOT_CONFIRMED_EMPTY,
                    pin_known=None,
                    is_active=None,
                    warnings=[],
                )
                continue
            was_active = code.is_active
            logger.info(
                "Slot %d on %s (code_id=%d) is empty: %s",
                slot_index,
                lock_entity_id,
                code.id,
                "deactivating and releasing the slot" if was_active else "releasing the slot",
            )
            # The code row before its assignment row, like every writer of both,
            # including a code that's already off and only loses its slot here.
            DoorCode.objects.select_for_update().filter(id=code.id).first()
            if was_active:
                code.is_active = False
                code.save(update_fields=["is_active", "updated_at"])
                result.deactivated += 1
            touched_code_ids.add(code.id)
            assignment.slot_index = None
            # Nothing left on this lock, so per lock it's pending, attempts kept (issue #126).
            assignment.push_state = DoorCode.PushState.PENDING
            assignment.schedule_pending = False
            assignment.save(update_fields=["slot_index", "push_state", "schedule_pending", "updated_at"])
            # Confirmed empty live: its PIN comes off the other locks too (issue #221).
            taken_off = _take_off_other_locks(code=code, lock_entity_id=lock_entity_id) if off_verdict else []
            DoorCodeEvent.objects.create(
                door_code=code,
                user=actor_user,
                lock_entity_id=lock_entity_id,
                event_type=DoorCodeEvent.EventType.CODE_SYNCED,
                metadata={
                    "slot_index": slot_index,
                    "action": "deactivated" if was_active else "slot_released",
                    # After the flags, so the reconcile sees them as set by this (off_clear_q).
                    **({OFF_CONFIRMED_KEY: True, "taken_off_lock_entity_ids": taken_off} if off_verdict else {}),
                },
            )

        _flag_duplicate_pins(
            lock_entity_id=lock_entity_id,
            pin_by_slot=pin_by_slot,
            slot_results=slot_results,
            slot_events=slot_events,
        )

        # The code-level state is the rollup of the locks, so a code the sync
        # converted, turned off or released a slot of gets it worked out again
        # (issue #126). Still in the sync's transaction.
        from locks.use_cases.lock_push import refresh_push_state

        for code_id in sorted(touched_code_ids):
            refresh_push_state(door_code=DoorCode(id=code_id))

        result.timestamp = django_timezone.now()

        # Persist last_synced_at on the lock entity's attributes (ADR 0069 finding 12).
        if not dry_run:
            try:
                entity = Entity.objects.filter(entity_id=lock_entity_id).first()
                if entity:
                    attrs = entity.attributes or {}
                    zw = attrs.get("zwavejs") if isinstance(attrs, dict) else {}
                    if not isinstance(zw, dict):
                        zw = {}
                    zw["last_synced_at"] = result.timestamp.isoformat()
                    attrs["zwavejs"] = zw
                    entity.attributes = attrs
                    entity.save(update_fields=["attributes", "updated_at"])
            except Exception:
                logger.warning("Failed to persist last_synced_at for %s", lock_entity_id, exc_info=True)

        logger.info(
            "Lock config sync complete for %s (node %d): created=%d updated=%d unchanged=%d "
            "deactivated=%d skipped=%d errors=%d",
            lock_entity_id,
            node_id,
            result.created,
            result.updated,
            result.unchanged,
            result.deactivated,
            result.skipped,
            result.errors,
        )

        # Emit dispatcher event so rules referencing this lock can react (ADR 0069 finding 14).
        if not dry_run and (result.created or result.updated or result.deactivated):
            try:
                from alarm.dispatcher import notify_entities_changed

                notify_entities_changed(
                    source="lock_config_sync",
                    entity_ids=[lock_entity_id],
                    changed_at=result.timestamp,
                )
            except Exception:
                logger.warning("Failed to notify dispatcher after sync for %s", lock_entity_id, exc_info=True)

        return result
