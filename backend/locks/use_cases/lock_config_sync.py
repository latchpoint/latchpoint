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
from alarm.crypto import InvalidToken, SettingsEncryption
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
# operation on the same lock (a push, a config sync) before giving up.
SYNC_LOCK_WAIT_SECONDS = 30.0
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
_WARN_DUPLICATE_PIN = "duplicate_pin"


def _has_outstanding_slot_cleanup(*, door_code: DoorCode) -> bool:
    """Whether a slot may still hold an older PIN of ``door_code``: a clear that hasn't
    gone through yet (#144) or an unconfirmed push still in its window (#111)."""
    from locks.use_cases.lock_push import has_unconfirmed_attempt_slots, unresolved_clear_failures

    return bool(unresolved_clear_failures(door_code=door_code)) or has_unconfirmed_attempt_slots(door_code=door_code)


def _slots_with_outstanding_cleanup(*, lock_entity_id: str) -> dict[int, int]:
    """Untracked slots on this lock that a code still has a clear or unconfirmed push on record for.

    Maps slot -> door code id. The sync doesn't import those slots as new codes,
    since that code's own retry reads them back and clears them (issue #150).
    """
    from locks.use_cases.lock_push import (
        _CLEAR_FAILED_ACTION,
        _UNCONFIRMED_PUSH_ACTION,
        _unconfirmed_attempt_slots,
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
    slots: dict[int, int] = {}
    for door_code in DoorCode.objects.filter(id__in=list(code_ids)).order_by("id"):
        for failure in unresolved_clear_failures(door_code=door_code):
            if failure.lock_entity_id == lock_entity_id:
                slots.setdefault(int(failure.slot_index), door_code.id)
        for slot_index in _unconfirmed_attempt_slots(door_code=door_code, lock_entity_id=lock_entity_id):
            slots.setdefault(int(slot_index), door_code.id)
    return slots


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


def _duplicate_pin_code_ids(
    *, assigned_pins: list[tuple[int, int | None, str]], slot_index: int, pin: str | None
) -> list[int]:
    """Codes on this lock whose PIN ``slot_index`` holds while it isn't their tracked slot (issue #140).

    Catches copies stranded before #136 (#133), which nothing tracks. Only
    flagged; the sync never clears a slot.
    """
    if pin is None:
        return []
    return sorted(
        {code_id for code_id, tracked, code_pin in assigned_pins if code_pin == pin and tracked != slot_index}
    )


def _existing_code_skip_reason(*, code: DoorCode, raw_pin: str | None) -> str | None:
    """Why the sync must leave the code tracked in this slot alone, or ``None`` to reconcile it (issue #150).

    - any code with a clear or unconfirmed push still outstanding: its slot may
      hold an older PIN and taking ``is_active`` from the lock could switch on a
      code #144 turned off
    - a manual code that's off: latchpoint turned it off, so the PIN still in its
      slot is a clear that hasn't happened, not the lock's say
    - a manual code whose slot holds a different PIN: flagged, never adopted
    """
    if _has_outstanding_slot_cleanup(door_code=code):
        return _SKIP_CLEAR_OUTSTANDING
    if code.source == DoorCode.Source.SYNCED:
        return None
    if not code.is_active:
        return _SKIP_INACTIVE_MANUAL_CODE
    if raw_pin is not None:
        from locks.use_cases.lock_push import decrypt_pin_or_none

        if decrypt_pin_or_none(code) != raw_pin:
            return _SKIP_PIN_MISMATCH
    return None


def _record_sync_skip(
    *, code: DoorCode, actor_user: User, lock_entity_id: str, slot_index: int, reason: str, pin_known: bool
) -> None:
    DoorCodeEvent.objects.create(
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

        # Read before anything below changes the assignments or PINs.
        outstanding_cleanup_by_slot = _slots_with_outstanding_cleanup(lock_entity_id=lock_entity_id)
        assigned_pins = _assigned_code_pins(lock_entity_id=lock_entity_id)

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
            duplicate_pin_ids = _duplicate_pin_code_ids(assigned_pins=assigned_pins, slot_index=slot_index, pin=raw_pin)
            if duplicate_pin_ids:
                warnings.append(_WARN_DUPLICATE_PIN)
                logger.warning(
                    "Slot %d on %s holds the PIN of door code(s) %s, which don't track that slot",
                    slot_index,
                    lock_entity_id,
                    duplicate_pin_ids,
                )

            skip_code: DoorCode | None = None
            skip_reason: str | None = None
            if existing:
                skip_reason = _existing_code_skip_reason(code=existing.door_code, raw_pin=raw_pin)
                skip_code = existing.door_code if skip_reason else None
            elif slot_index in outstanding_cleanup_by_slot:
                skip_reason = _SKIP_CLEAR_OUTSTANDING
                skip_code = DoorCode.objects.filter(id=outstanding_cleanup_by_slot[slot_index]).first()
            if skip_reason and skip_code is not None:
                logger.warning(
                    "Slot %d on %s: skipped (%s, code_id=%d)", slot_index, lock_entity_id, skip_reason, skip_code.id
                )
                _record_sync_skip(
                    code=skip_code,
                    actor_user=actor_user,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
                    reason=skip_reason,
                    pin_known=pin_known,
                )
                result.skipped += 1
                result.slots.append(
                    SlotSyncResult(
                        slot_index=slot_index,
                        action="skipped",
                        door_code_id=skip_code.id,
                        pin_known=pin_known,
                        is_active=bool(is_active) if is_active is not None else None,
                        warnings=[*warnings, skip_reason],
                        duplicate_pin_door_code_ids=duplicate_pin_ids,
                    )
                )
                continue

            if existing:
                code = existing.door_code
                updated_fields: list[str] = []
                # A manual code only gets here when the slot holds its PIN or a
                # masked one, so its own PIN stays (issue #150).
                converting = code.source != DoorCode.Source.SYNCED

                if code.user_id != target_user.id:
                    code.user = target_user
                    updated_fields.append("user")
                    warnings.append("owner_changed")

                if code.source != DoorCode.Source.SYNCED:
                    code.source = DoorCode.Source.SYNCED
                    updated_fields.append("source")

                enc = SettingsEncryption.get()
                if not converting:
                    if raw_pin is not None:
                        stored_pin = None
                        if code.encrypted_pin:
                            with contextlib.suppress(ValueError, InvalidToken):
                                stored_pin = enc.decrypt(code.encrypted_pin)
                        if stored_pin != raw_pin:
                            code.encrypted_pin = enc.encrypt(raw_pin)
                            updated_fields.append("encrypted_pin")
                    elif code.encrypted_pin is not None:
                        code.encrypted_pin = None
                        updated_fields.append("encrypted_pin")
                    if code.pin_length != pin_length:
                        code.pin_length = pin_length
                        updated_fields.append("pin_length")
                if is_active is not None and code.is_active != bool(is_active):
                    code.is_active = bool(is_active)
                    updated_fields.append("is_active")

                schedule_applied = False
                schedule_unsupported = bool(schedule_unsupported_reason)
                if not schedule_unsupported:
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
                    action = "updated"
                    result.updated += 1
                    logger.info("Slot %d on %s: updated (fields: %s)", slot_index, lock_entity_id, updated_fields)
                else:
                    result.unchanged += 1
                    logger.debug("Slot %d on %s: unchanged", slot_index, lock_entity_id)

                DoorCodeEvent.objects.create(
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
                        **({"duplicate_pin_door_code_ids": duplicate_pin_ids} if duplicate_pin_ids else {}),
                    },
                )

                result.slots.append(
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
                        duplicate_pin_door_code_ids=duplicate_pin_ids,
                    )
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
                DoorCodeLockAssignment.objects.create(
                    door_code=code,
                    lock_entity_id=lock_entity_id,
                    slot_index=slot_index,
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
                    existing_code.encrypted_pin = (
                        SettingsEncryption.get().encrypt(raw_pin) if raw_pin is not None else None
                    )
                    existing_code.pin_length = pin_length
                    if is_active is not None:
                        existing_code.is_active = bool(is_active)
                    existing_code.save(update_fields=["encrypted_pin", "pin_length", "is_active", "updated_at"])
                    result.updated += 1
                    result.slots.append(
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

            DoorCodeEvent.objects.create(
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
                    **({"duplicate_pin_door_code_ids": duplicate_pin_ids} if duplicate_pin_ids else {}),
                },
            )

            result.created += 1
            logger.info(
                "Slot %d on %s: created (code_id=%d, pin_known=%s)", slot_index, lock_entity_id, code.id, pin_known
            )
            result.slots.append(
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
                    duplicate_pin_door_code_ids=duplicate_pin_ids,
                )
            )

        # Turn off synced codes whose slot read back empty and stop tracking the slot.
        # A slot whose read failed or was inconclusive isn't touched: its PIN may
        # still be on the lock (issue #149).
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
            if not code or code.source != DoorCode.Source.SYNCED:
                continue
            was_active = code.is_active
            logger.info(
                "Slot %d on %s (code_id=%d) is empty: %s",
                slot_index,
                lock_entity_id,
                code.id,
                "deactivating and releasing the slot" if was_active else "releasing the slot",
            )
            assignment.slot_index = None
            assignment.save(update_fields=["slot_index", "updated_at"])
            if was_active:
                code.is_active = False
                code.save(update_fields=["is_active", "updated_at"])
                result.deactivated += 1
            DoorCodeEvent.objects.create(
                door_code=code,
                user=actor_user,
                lock_entity_id=lock_entity_id,
                event_type=DoorCodeEvent.EventType.CODE_SYNCED,
                metadata={
                    "slot_index": slot_index,
                    "action": "deactivated" if was_active else "slot_released",
                },
            )

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
