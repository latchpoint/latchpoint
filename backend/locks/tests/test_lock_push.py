"""Tests for ADR 0092 push_door_code_to_lock."""

from __future__ import annotations

import contextlib
import json
from datetime import time, timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from integrations_zwavejs.cc_api_contracts import validate_cc_api_args
from integrations_zwavejs.manager import ZwavejsNotConfigured
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import Entity
from alarm.tests.settings_test_utils import EncryptionTestMixin
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_push import (
    InvalidPin,
    LockPushFailed,
    LockRejectedCode,
    LockSlotsFull,
    LockUnreachable,
    push_door_code_to_assigned_locks,
    push_door_code_to_lock,
    sanitize_push_error_for_storage,
)


def _value_id_key(value_id: dict) -> str:
    return f"{value_id.get('commandClass')}:{value_id.get('property')}:{value_id.get('propertyKey')}"


class FakeGateway:
    """Records invoke_cc_api calls and serves canned slot reads from a script.

    Models two things separately, like the real stack:

    * the physical lock (``_lock_codes``), which stores what CC 99 ``set`` sends
      unless the PIN is in ``reject_pins`` for that node or already sits in
      another slot (Yale drops duplicates; ``drops_duplicates=False`` turns that
      off), and answers CC 99 ``get`` from it;
    * the Z-Wave JS value cache read by ``node_get_value``. ``slot_status`` seeds
      it. By default a stored ``set`` does not reach it until
      ``deliver_late_reports()`` runs, which is the stale cache #106 depends on
      (and a report arriving after the readback gave up). Pass
      ``cache_updates_on_set=True`` to update it right away.

    ``get_responses`` scripts the readback: a list (any node) or a dict of
    node_id -> list. Each entry is returned (or raised, if an exception) by one
    ``get`` call, falling back to the lock's real state once the script runs out.

    ``admin_code`` / ``master_code`` are what the Z-Wave JS value cache exposes
    as CC 99 ``adminCode`` / ``masterCode``. ``lock_admin_code`` is the admin
    code the lock really has, which defaults to the cached one, and the lock
    drops a ``set`` of that PIN like a Yale does (issue #107). Pass a different
    one (``""`` for none) to model a stale cache (issue #125). ``set_result`` is
    what every CC 99 ``set`` returns (a Supervision result, or ``None``).
    """

    def __init__(
        self,
        *,
        usersNumber: int = 5,
        slot_status: dict[int, int] | None = None,
        invoke_raises: Exception | None = None,
        invoke_raises_after: int | None = None,
        admin_code: str | None = None,
        master_code: str | None = None,
        lock_admin_code: str | None = None,
        set_result: object = None,
        get_responses: list | dict[int, list] | None = None,
        reject_pins: dict[int, set[str]] | None = None,
        cache_updates_on_set: bool = False,
        drops_duplicates: bool = True,
    ):
        self._usersNumber = usersNumber
        self._slot_status = slot_status or {}
        self._invoke_raises = invoke_raises
        self._invoke_raises_after = invoke_raises_after
        self._admin_code = admin_code
        self._master_code = master_code
        self._lock_admin_code = lock_admin_code if lock_admin_code is not None else (admin_code or master_code or "")
        self._set_result = set_result
        if isinstance(get_responses, dict):
            self._get_scripts = {node: list(script) for node, script in get_responses.items()}
        else:
            self._get_scripts = {None: list(get_responses or [])}
        self._reject_pins = reject_pins or {}
        self._cache_updates_on_set = cache_updates_on_set
        self._drops_duplicates = drops_duplicates
        self._lock_codes: dict[tuple[int, int], str] = {}
        self._cache_codes: dict[tuple[int, int], str] = {}
        self._late_reports: list[tuple[int, int, str]] = []
        self.invoke_calls: list[dict] = []
        # How many times node_get_defined_value_ids was called (issue #124).
        self.value_id_fetches = 0
        # (method_name, timeout_seconds) for every CC 99 call that got past validation.
        self.invoke_timeouts: list[tuple[str, float]] = []

    def deliver_late_reports(self) -> None:
        """Apply queued user-code reports to the value cache."""
        for node_id, slot, code in self._late_reports:
            self._cache_codes[(node_id, slot)] = code
        self._late_reports = []

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0):  # noqa: ARG002
        self.value_id_fetches += 1
        value_ids = [{"commandClass": 99, "property": "usersNumber"}]
        if self._admin_code is not None:
            value_ids.append({"commandClass": 99, "property": "adminCode"})
        if self._master_code is not None:
            value_ids.append({"commandClass": 99, "property": "masterCode"})
        for slot in range(1, self._usersNumber + 1):
            value_ids.append({"commandClass": 99, "property": "userIdStatus", "propertyKey": slot})
            value_ids.append({"commandClass": 99, "property": "userCode", "propertyKey": slot})
        return value_ids

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0):  # noqa: ARG002
        if value_id.get("property") == "usersNumber":
            return self._usersNumber
        if value_id.get("property") == "adminCode":
            return self._admin_code
        if value_id.get("property") == "masterCode":
            return self._master_code
        if value_id.get("property") == "userIdStatus":
            slot = int(value_id.get("propertyKey"))
            if (node_id, slot) in self._cache_codes:
                return 1
            return self._slot_status.get(slot, 0)
        if value_id.get("property") == "userCode":
            return self._cache_codes.get((node_id, int(value_id.get("propertyKey"))), "")
        return None

    def _handle_user_code_call(self, *, node_id: int, method_name: str, args: list):
        if method_name == "set":
            slot, pin = int(args[0]), str(args[2])
            held_elsewhere = self._drops_duplicates and any(
                n == node_id and s != slot and c == pin for (n, s), c in self._lock_codes.items()
            )
            matches_admin_code = bool(self._lock_admin_code) and pin == self._lock_admin_code
            if pin in self._reject_pins.get(node_id, set()) or held_elsewhere or matches_admin_code:
                return self._set_result  # the lock silently drops it; the set still "succeeds"
            self._lock_codes[(node_id, slot)] = pin
            if self._cache_updates_on_set:
                self._cache_codes[(node_id, slot)] = pin
            else:
                self._late_reports.append((node_id, slot, pin))
            return self._set_result
        if method_name == "clear":
            self._lock_codes.pop((node_id, int(args[0])), None)
            self._cache_codes.pop((node_id, int(args[0])), None)
            return None
        if method_name == "get":
            script = self._get_scripts.get(node_id) or self._get_scripts.get(None)
            if script:
                scripted = script.pop(0)
                if isinstance(scripted, Exception):
                    raise scripted
                return scripted
            code = self._lock_codes.get((node_id, int(args[0])))
            if code is not None:
                return {"userIdStatus": 1, "userCode": code}
            return {"userIdStatus": 0, "userCode": ""}
        return None

    def invoke_cc_api(
        self,
        *,
        node_id: int,
        command_class: int,
        method_name: str,
        args: list | None = None,
        timeout_seconds: float = 10.0,
    ):
        # Enforce the CC API contract on every recorded call. If a future change
        # to lock_push starts sending the wrong arg shape (the kind of bug that
        # bit prod with CC 99 set), this raises here instead of silently
        # recording bad args and "passing" the test.
        validate_cc_api_args(command_class=command_class, method_name=method_name, args=args)
        self.invoke_calls.append(
            {
                "node_id": node_id,
                "command_class": command_class,
                "method_name": method_name,
                "args": json.loads(json.dumps(args or [])),
            }
        )
        if command_class == 99:
            self.invoke_timeouts.append((method_name, timeout_seconds))
        if self._invoke_raises is not None and (
            self._invoke_raises_after is None or len(self.invoke_calls) > self._invoke_raises_after
        ):
            raise self._invoke_raises
        if command_class == 99:
            return self._handle_user_code_call(node_id=node_id, method_name=method_name, args=args or [])
        return None


class PushDoorCodeToLockTests(EncryptionTestMixin, TestCase):
    LOCK_ENTITY_ID = "lock.front_door"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )

    def _make_code(self, *, pin: str = "1234", **kwargs) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=kwargs.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=True,
            **kwargs,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        return code

    def test_picks_lowest_free_slot_and_calls_cc_99_set(self):
        # slot 1 occupied, slot 2 available
        gateway = FakeGateway(usersNumber=5, slot_status={1: 1, 2: 0, 3: 0, 4: 0, 5: 0})
        code = self._make_code(pin="1234")

        result = push_door_code_to_lock(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            zwavejs=gateway,
        )

        self.assertEqual(result.slot_index, 2)
        set_calls = [c for c in gateway.invoke_calls if c["method_name"] == "set" and c["command_class"] == 99]
        self.assertEqual(len(set_calls), 1)
        # Z-Wave JS CC 99 set: (userId, userIdStatus=1 "Occupied", userCode)
        self.assertEqual(set_calls[0]["args"], [2, 1, "1234"])

        # Assignment + push state updated.
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(assignment.slot_index, 2)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")
        self.assertIsNotNone(code.last_push_attempt_at)

        # code_synced event emitted with action=pushed.
        event = DoorCodeEvent.objects.get(door_code=code)
        self.assertEqual(event.event_type, DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertEqual(event.metadata.get("action"), "pushed")
        self.assertEqual(event.metadata.get("slot_index"), 2)
        self.assertFalse(event.metadata.get("schedule_applied"))

    def test_pushes_schedule_per_weekday_with_correct_duration(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        # Days mask: Mon (bit 0) + Wed (bit 2) = 0b101 = 5; window 09:00 → 17:30 = 8h30m.
        code = self._make_code(
            pin="5678",
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b101,
            window_start=time(9, 0),
            window_end=time(17, 30),
        )

        result = push_door_code_to_lock(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            zwavejs=gateway,
        )

        self.assertTrue(result.schedule_applied)
        self.assertEqual(sorted(result.weekdays_pushed), [1, 3])  # Mon=1, Wed=3

        schedule_calls = [
            c
            for c in gateway.invoke_calls
            if c["command_class"] == 78 and c["method_name"] == "setDailyRepeatingSchedule"
        ]
        self.assertEqual(len(schedule_calls), 2)
        for call in schedule_calls:
            # setDailyRepeatingSchedule(slot, schedule) — two positional args.
            slot, schedule = call["args"]
            self.assertEqual(slot["userId"], result.slot_index)
            self.assertIn(slot["slotId"], (1, 3))  # Mon=slot 1, Wed=slot 3 (bit+1)
            self.assertEqual(schedule["startHour"], 9)
            self.assertEqual(schedule["startMinute"], 0)
            self.assertEqual(schedule["durationHour"], 8)
            self.assertEqual(schedule["durationMinute"], 30)
            self.assertEqual(len(schedule["weekdays"]), 1)
            self.assertIn(schedule["weekdays"][0], (1, 3))

    def test_pushes_full_day_schedule_when_days_set_without_window(self):
        # The reported prod bug: days set (Sat+Sun) but no time window. Previously
        # this pushed only the PIN; now it must push a full-day CC 78 schedule so
        # the lock enforces the day restriction.
        gateway = FakeGateway(usersNumber=7, slot_status=dict.fromkeys(range(1, 8), 0))
        code = self._make_code(
            pin="4242",
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=96,  # bit5 (Sat) + bit6 (Sun)
        )

        result = push_door_code_to_lock(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            zwavejs=gateway,
        )

        self.assertTrue(result.schedule_applied)
        # CC 78 ScheduleEntryLockWeekday: Saturday=6, Sunday=0.
        self.assertEqual(sorted(result.weekdays_pushed), [0, 6])

        schedule_calls = [
            c
            for c in gateway.invoke_calls
            if c["command_class"] == 78 and c["method_name"] == "setDailyRepeatingSchedule"
        ]
        self.assertEqual(len(schedule_calls), 2)
        for call in schedule_calls:
            slot, schedule = call["args"]
            self.assertEqual(slot["userId"], result.slot_index)
            self.assertIn(slot["slotId"], (6, 7))  # Sat=slot 6, Sun=slot 7 (bit+1)
            self.assertEqual(schedule["startHour"], 0)
            self.assertEqual(schedule["startMinute"], 0)
            self.assertEqual(schedule["durationHour"], 23)
            self.assertEqual(schedule["durationMinute"], 59)
            self.assertEqual(len(schedule["weekdays"]), 1)
            self.assertIn(schedule["weekdays"][0], (0, 6))

        # The PIN's event says the schedule is pending, the schedule's own event that it landed (issue #123).
        pushed, scheduled = DoorCodeEvent.objects.filter(door_code=code).order_by("id")
        self.assertEqual(pushed.metadata.get("action"), "pushed")
        self.assertTrue(pushed.metadata.get("schedule_pending"))
        self.assertEqual(scheduled.metadata.get("action"), "schedule_pushed")
        self.assertTrue(scheduled.metadata.get("schedule_applied"))

    def test_full_day_schedule_uses_correct_weekday_enum(self):
        # No window, Mon (bit0) + Wed (bit2): enum maps Mon=1, Wed=3.
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(
            pin="1357",
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b101,
        )

        result = push_door_code_to_lock(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            zwavejs=gateway,
        )

        self.assertTrue(result.schedule_applied)
        self.assertEqual(sorted(result.weekdays_pushed), [1, 3])

    def test_no_schedule_pushed_when_days_of_week_none(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234", code_type=DoorCode.CodeType.TEMPORARY)  # days_of_week=None

        result = push_door_code_to_lock(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            zwavejs=gateway,
        )

        self.assertFalse(result.schedule_applied)
        self.assertEqual(result.weekdays_pushed, [])
        schedule_calls = [c for c in gateway.invoke_calls if c["command_class"] == 78]
        self.assertEqual(schedule_calls, [])

    def test_schedule_window_end_before_start_raises_invalid_pin(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(
            pin="2222",
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,  # Monday
            window_start=time(17, 0),
            window_end=time(9, 0),  # end <= start
        )

        with self.assertRaises(InvalidPin):
            push_door_code_to_lock(
                door_code=code,
                lock_entity_id=self.LOCK_ENTITY_ID,
                zwavejs=gateway,
            )

    def test_slots_full_raises_before_any_network_write(self):
        # Every slot occupied.
        gateway = FakeGateway(usersNumber=2, slot_status={1: 1, 2: 1})
        code = self._make_code(pin="1111")

        with self.assertRaises(LockSlotsFull):
            push_door_code_to_lock(
                door_code=code,
                lock_entity_id=self.LOCK_ENTITY_ID,
                zwavejs=gateway,
            )

        set_calls = [c for c in gateway.invoke_calls if c["method_name"] == "set"]
        self.assertEqual(set_calls, [])

        code.refresh_from_db()
        # push_state stays pending since this is a validation-shaped failure that
        # the caller should surface as 409 — no DB-state mutation needed.
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

    def test_invalid_pin_raises_before_any_network_call(self):
        # Code without an encrypted PIN.
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="",
            pin_length=None,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})

        with self.assertRaises(InvalidPin):
            push_door_code_to_lock(
                door_code=code,
                lock_entity_id=self.LOCK_ENTITY_ID,
                zwavejs=gateway,
            )

        # Never reached the gateway.
        self.assertEqual(gateway.invoke_calls, [])

    def test_transient_gateway_error_leaves_row_pending_for_retry(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        # First invoke (the CC 99 set) raises.
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            invoke_raises=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            invoke_raises_after=0,
        )
        code = self._make_code(pin="1234")

        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(
                door_code=code,
                lock_entity_id=self.LOCK_ENTITY_ID,
                zwavejs=gateway,
            )

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn("ZwavejsCommandError", code.last_push_error)
        self.assertIsNotNone(code.last_push_attempt_at)

        # Slot was not claimed.
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertIsNone(assignment.slot_index)

    def test_terminal_config_error_marks_failed_and_emits_event(self):
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            invoke_raises=ZwavejsNotConfigured("ws_url not set"),
            invoke_raises_after=0,
        )
        code = self._make_code(pin="1234")

        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(
                door_code=code,
                lock_entity_id=self.LOCK_ENTITY_ID,
                zwavejs=gateway,
            )

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)

        failed_events = DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_FAILED)
        self.assertEqual(failed_events.count(), 1)
        self.assertEqual(failed_events.first().metadata.get("action"), "push")

    def test_lock_without_zwavejs_node_id_records_terminal_failure(self):
        """Entity exists but has no ``attributes.zwavejs.node_id`` — must not stall at pending."""
        Entity.objects.filter(entity_id=self.LOCK_ENTITY_ID).update(attributes={})
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234")

        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(
                door_code=code,
                lock_entity_id=self.LOCK_ENTITY_ID,
                zwavejs=gateway,
            )

        # Never reached the gateway — failed at config resolution.
        self.assertEqual(gateway.invoke_calls, [])

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertIn("Z-Wave JS node", code.last_push_error)
        self.assertIsNotNone(code.last_push_attempt_at)

    def test_unknown_lock_entity_records_terminal_failure(self):
        """The lock_entity_id does not exist in Entity — push must terminate, not silently stall."""
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234")
        # The failure goes on that lock, and the code is the rollup of its locks (issue #126).
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id="lock.does_not_exist")

        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(
                door_code=code,
                lock_entity_id="lock.does_not_exist",
                zwavejs=gateway,
            )

        self.assertEqual(gateway.invoke_calls, [])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertTrue(code.last_push_error)

    def test_pin_redacted_in_invoke_cc_api_debug_log(self):
        """ADR 0092 §7: PIN bytes must never reach DEBUG logs."""
        from integrations_zwavejs.manager import _redact_cc_api_args_for_log

        redacted = _redact_cc_api_args_for_log(command_class=99, method_name="set", args=[3, 1, "9876"])
        self.assertEqual(redacted, [3, 1, "***"])

        # Other CC/method combos pass through unchanged.
        unchanged = _redact_cc_api_args_for_log(
            command_class=78, method_name="setDailyRepeatingSchedule", args=[{"userId": 1}]
        )
        self.assertEqual(unchanged, [{"userId": 1}])


class DoorCodeCreatePushIntegrationTests(EncryptionTestMixin, TestCase):
    """Verify create_door_code wires through the push pipeline."""

    LOCK_ENTITY_ID = "lock.back_door"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Back Door",
            attributes={"zwavejs": {"node_id": 11}},
            source="home_assistant",
        )

    def test_create_door_code_pushes_to_assigned_lock(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})

        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code="2468",
            label="Cleaner",
            lock_entity_ids=[self.LOCK_ENTITY_ID],
            actor_user=self.user,
            zwavejs=gateway,
        )

        set_calls = [c for c in gateway.invoke_calls if c["method_name"] == "set" and c["command_class"] == 99]
        self.assertEqual(len(set_calls), 1)
        self.assertEqual(set_calls[0]["args"][0], 1)
        # userIdStatus=1 ("Occupied") and PIN reach the gateway args.
        self.assertEqual(set_calls[0]["args"][1], 1)
        self.assertEqual(set_calls[0]["args"][2], "2468")

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_pin_change_clears_old_slot_before_repushing(self):
        """A PIN change must remove the old PIN from the lock; otherwise both PINs would be active."""
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})

        # First create + push lands the code at slot 1.
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code="1111",
            label="Tenant",
            lock_entity_ids=[self.LOCK_ENTITY_ID],
            actor_user=self.user,
            zwavejs=gateway,
        )
        code.refresh_from_db()
        self.assertEqual(code.lock_assignments.first().slot_index, 1)

        # The lock now reports slot 1 as occupied. If the re-push doesn't clear it
        # first, the second push will pick slot 2 and strand the old PIN.
        gateway = FakeGateway(usersNumber=3, slot_status={1: 1, 2: 0, 3: 0})

        door_codes_uc.update_door_code(
            code=code,
            changes={"code": "2222"},
            actor_user=self.user,
            zwavejs=gateway,
        )

        clears = [c for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "clear"]
        self.assertEqual(len(clears), 1, "Old slot must be cleared before re-push")
        self.assertEqual(clears[0]["args"], [1])

    def test_is_active_false_clears_lock_without_repush(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code="3333",
            label="Cleaner",
            lock_entity_ids=[self.LOCK_ENTITY_ID],
            actor_user=self.user,
            zwavejs=gateway,
        )

        gateway = FakeGateway(usersNumber=3, slot_status={1: 1, 2: 0, 3: 0})
        door_codes_uc.update_door_code(
            code=code,
            changes={"is_active": False},
            actor_user=self.user,
            zwavejs=gateway,
        )

        clears = [c for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "clear"]
        self.assertEqual(len(clears), 1, "Deactivation must clear the slot on the lock")

        # No CC 99 set call — we don't re-push a deactivated code.
        sets = [c for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "set"]
        self.assertEqual(sets, [])


class PushPendingSchedulerTaskTests(EncryptionTestMixin, TestCase):
    LOCK_ENTITY_ID = "lock.garage"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Garage",
            attributes={"zwavejs": {"node_id": 9}},
            source="home_assistant",
        )

    def test_task_picks_up_pending_codes_with_unassigned_slots(self):
        from locks.tasks import push_pending_door_codes

        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("1357"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=DoorCode.PushState.PENDING,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            attempted = push_pending_door_codes()

        self.assertEqual(attempted, 1)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_task_marks_failed_after_max_attempts(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        from locks.tasks import push_pending_door_codes

        gateway = FakeGateway(
            usersNumber=2,
            slot_status={1: 0, 2: 0},
            invoke_raises=ZwavejsCommandError("driver TimeoutError after 5.0s"),
            invoke_raises_after=0,
        )
        # Start the lock 1 tick away from the 24-attempt cap so this tick trips it.
        # The cap is per lock now (issue #126).
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("2222"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=DoorCode.PushState.PENDING,
        )
        assignment = DoorCodeLockAssignment.objects.create(
            door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, push_attempt_count=23
        )

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        assignment.refresh_from_db()
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.FAILED, 24))
        cap_event = (
            DoorCodeEvent.objects.filter(
                door_code=code, event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__reason="max_attempts_exceeded"
            )
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(cap_event)


class PushReadbackAndAdminCodeTests(EncryptionTestMixin, TestCase):
    """Issue #107: a returned CC 99 set is not proof the lock stored the code."""

    LOCK_ENTITY_ID = "lock.back_door"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Back Door",
            attributes={"zwavejs": {"node_id": 12}},
            source="home_assistant",
        )
        # No real sleeping between readback attempts.
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_code(self, *, pin: str = "1234", **kwargs) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=kwargs.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=True,
            **kwargs,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        return code

    def _push(self, code: DoorCode, gateway: FakeGateway):
        return push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

    @staticmethod
    def _calls(gateway: FakeGateway, method_name: str, command_class: int = 99) -> list[dict]:
        return [
            c for c in gateway.invoke_calls if c["command_class"] == command_class and c["method_name"] == method_name
        ]

    @staticmethod
    def _cleared_slots(gateway: FakeGateway) -> list[int]:
        return [c["args"][0] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "clear"]

    @staticmethod
    def _unconfirmed_slots(code: DoorCode) -> list[int]:
        return [
            e.metadata["slot_index"]
            for e in DoorCodeEvent.objects.filter(door_code=code).order_by("id")
            if e.metadata.get("action") == lock_push_uc._UNCONFIRMED_PUSH_ACTION
        ]

    def _assert_terminal_failure(self, code: DoorCode, *, error_contains: str) -> None:
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertIn(error_contains, code.last_push_error)
        # Counted on the lock; the code's own count only counts clear retries (issue #126).
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(
            (assignment.push_state, assignment.push_attempt_count, code.push_attempt_count),
            (DoorCode.PushState.FAILED, 1, 0),
        )
        self.assertIsNone(assignment.slot_index)
        self.assertTrue(
            DoorCodeEvent.objects.filter(
                door_code=code, event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__action="push"
            ).exists()
        )
        self.assertFalse(
            DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED).exists()
        )

    def test_matching_readback_marks_pushed(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 1, 2: 0, 3: 0})
        code = self._make_code(pin="4321")

        result = self._push(code, gateway)

        self.assertEqual(result.slot_index, 2)
        # Readback of the same slot happens right after the set.
        self.assertEqual([c["method_name"] for c in gateway.invoke_calls], ["set", "get"])
        self.assertEqual(self._calls(gateway, "get")[0]["args"], [2])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_empty_slot_readback_is_terminal_failure(self):
        # The Yale case from #107: set returns, slot reads back Available with no code.
        gateway = FakeGateway(usersNumber=3, slot_status={1: 1, 2: 0, 3: 0}, reject_pins={12: {"4321"}})
        code = self._make_code(pin="4321", days_of_week=0b1)

        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="slot 2 reads back empty")
        # An empty answer is asked once more before it counts.
        self.assertEqual(len(self._calls(gateway, "get")), 2)
        # Best-effort clear in case the lock committed the write late.
        self.assertEqual(self._cleared_slots(gateway), [2])
        # No schedule pushed to a slot the lock doesn't hold.
        self.assertEqual(self._calls(gateway, "setDailyRepeatingSchedule", command_class=78), [])

    def test_empty_readback_then_stored_code_marks_pushed(self):
        # A lock still committing the write can answer Available right after the set.
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 0, "userCode": ""}],
        )
        code = self._make_code(pin="4321")

        self._push(code, gateway)

        self.assertEqual(len(self._calls(gateway, "get")), 2)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_empty_readback_then_no_answer_stays_pending_and_retry_adopts(self):
        # One empty answer then silence is the "still committing" case, not a
        # verdict. It used to be terminal, which stopped the scheduler; now it's
        # pending with the slot recorded, and the retry adopts it once it reads back.
        from integrations_zwavejs.manager import ZwavejsCommandError

        from locks.tasks import push_pending_door_codes

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 0, "userCode": ""}, timeout, timeout],
        )
        code = self._make_code(pin="4321", push_state=DoorCode.PushState.PENDING)

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn("LockCodeUnverified", code.last_push_error)
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=code).slot_index)
        self.assertEqual(self._unconfirmed_slots(code), [1])
        self.assertEqual(self._cleared_slots(gateway), [])

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 1)
        self.assertEqual(len(self._calls(gateway, "set")), 1)
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertIs(synced.metadata.get("adopted_existing_slot"), True)

    def test_disabled_readback_is_terminal_failure(self):
        # We send userIdStatus=1 (enabled); a code stored disabled won't open the door.
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 2, "userCode": "4321"}],
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="reports it disabled")
        # The lock still holds the PIN; clear it so re-enabling the slot can't open the door.
        self.assertEqual(self._cleared_slots(gateway), [1])
        self.assertNotIn((12, 1), gateway._lock_codes)

    def test_disabled_readback_with_a_different_code_is_not_cleared(self):
        # Our set was dropped and the slot holds someone else's disabled code.
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 2, "userCode": "9999"}],
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="holds a different code")
        self.assertEqual(self._cleared_slots(gateway), [])

    def test_disabled_readback_with_a_masked_code_is_not_cleared(self):
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 2, "userCode": "****"}],
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="can't be read back")
        self.assertEqual(self._cleared_slots(gateway), [])

    def test_disabled_readback_clear_failure_still_fails_and_warns(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        class ClearFailsGateway(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                result = super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )
                if command_class == 99 and method_name == "clear":
                    raise ZwavejsCommandError("driver TimeoutError after 5.0s")
                return result

        gateway = ClearFailsGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 2, "userCode": "4321"}],
        )
        code = self._make_code(pin="4321")

        with self.assertLogs("locks.use_cases.lock_push", level="WARNING") as logs, self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self.assertIn("Could not clear slot 1", "\n".join(logs.output))
        self.assertEqual(self._cleared_slots(gateway), [1])
        self._assert_terminal_failure(code, error_contains="reports it disabled")

    def test_mismatched_readback_code_is_terminal_failure(self):
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 1, "userCode": "9999"}],
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="holds a different code")
        self.assertNotIn("9999", code.last_push_error)
        self.assertNotIn("4321", code.last_push_error)
        # Someone else's code is in that slot; never clear it.
        self.assertEqual(self._cleared_slots(gateway), [])

    def test_readback_timeout_then_success_on_retry_marks_pushed(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[ZwavejsCommandError("driver TimeoutError after 5.0s")],
        )
        code = self._make_code(pin="4321")

        result = self._push(code, gateway)

        self.assertEqual(result.slot_index, 1)
        self.assertEqual(len(self._calls(gateway, "get")), 2)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 1)

    def test_readback_unknown_status_is_retried(self):
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[None, {"userIdStatus": 254, "userCode": ""}],
        )
        code = self._make_code(pin="4321")

        self._push(code, gateway)

        self.assertEqual(len(self._calls(gateway, "get")), 3)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_readback_retries_exhausted_leaves_row_pending_for_scheduler(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[timeout, timeout, timeout],
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        self.assertEqual(len(self._calls(gateway, "get")), 1 + len(lock_push_uc._READBACK_RETRY_DELAYS_SECONDS))
        code.refresh_from_db()
        # Same shape as a timed-out set: pending + attempt counted, slot not claimed.
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn("LockCodeUnverified", code.last_push_error)
        self.assertIn("TimeoutError", code.last_push_error)
        # Counted on the lock; the code's own count only counts clear retries (issue #126).
        self.assertEqual(code.push_attempt_count, 0)
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.PENDING, 1))
        self.assertIsNone(assignment.slot_index)
        self.assertFalse(
            DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED).exists()
        )
        # The slot the PIN went to is recorded so the retry can adopt it.
        self.assertEqual(self._unconfirmed_slots(code), [1])

    def test_masked_readback_code_on_occupied_slot_is_accepted(self):
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            get_responses=[{"userIdStatus": 1, "userCode": "****"}],
        )
        code = self._make_code(pin="4321")

        with self.assertLogs("locks.use_cases.lock_push", level="WARNING") as logs:
            self._push(code, gateway)

        self.assertIn("masked or unreadable", "\n".join(logs.output))
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_readback_without_user_code_field_is_accepted_with_warning(self):
        # A wrong/missing field name must not pass silently.
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, get_responses=[{"userIdStatus": 1}])
        code = self._make_code(pin="4321")

        with self.assertLogs("locks.use_cases.lock_push", level="WARNING") as logs:
            self._push(code, gateway)

        self.assertIn("missing from the report", "\n".join(logs.output))

    def test_pin_matching_a_stale_cached_admin_code_is_still_pushed(self):
        # Issue #125: the admin code was changed at the keypad since Z-Wave JS cached it.
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321", lock_admin_code="0000")
        code = self._make_code(pin="4321")

        result = self._push(code, gateway)

        self.assertEqual(result.slot_index, 1)
        self.assertEqual([c["method_name"] for c in gateway.invoke_calls], ["set", "get"])
        self.assertEqual(gateway._lock_codes, {(12, 1): "4321"})
        code.refresh_from_db()
        self.assertEqual((code.push_state, code.last_push_error), (DoorCode.PushState.PUSHED, ""))

    def _assert_admin_code_hint_without_the_code(self, code: DoorCode, exc: Exception, logs) -> None:
        code.refresh_from_db()
        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, str(exc))
        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, code.last_push_error)
        failed = DoorCodeEvent.objects.get(
            door_code=code, event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__action="push"
        )
        self.assertIs(failed.metadata.get("may_match_admin_code"), True)
        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, failed.metadata["reason"])
        # The admin code (which is the PIN here) is in none of them, not even masked by the sanitizer.
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        for text in (str(exc), code.last_push_error, assignment.last_push_error, json.dumps(failed.metadata)):
            self.assertNotIn("4321", text)
        self.assertNotIn("4321", "\n".join(logs.output))

    def test_empty_readback_of_a_pin_matching_the_cached_admin_code_says_it_may_match(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321")
        code = self._make_code(pin="4321")

        with (
            self.assertLogs("locks.use_cases.lock_push", level="DEBUG") as logs,
            self.assertRaises(LockRejectedCode) as ctx,
        ):
            self._push(code, gateway)

        # The set went out and the lock dropped it, like the Yale in #107.
        self.assertEqual(len(self._calls(gateway, "set")), 1)
        self._assert_terminal_failure(code, error_contains="slot 1 reads back empty")
        self._assert_admin_code_hint_without_the_code(code, ctx.exception, logs)
        self.assertEqual(self._cleared_slots(gateway), [1])

    def test_master_code_is_checked_when_the_node_has_no_admin_code(self):
        # Nodes interviewed before Z-Wave JS renamed masterCode to adminCode (issue #125).
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, master_code="4321")
        exposed = [v.get("property") for v in gateway.node_get_defined_value_ids(node_id=12)]
        self.assertNotIn("adminCode", exposed)
        code = self._make_code(pin="4321")

        with (
            self.assertLogs("locks.use_cases.lock_push", level="DEBUG") as logs,
            self.assertRaises(LockRejectedCode) as ctx,
        ):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="reads back empty")
        self._assert_admin_code_hint_without_the_code(code, ctx.exception, logs)

    def test_master_code_is_checked_alongside_a_different_admin_code(self):
        gateway = FakeGateway(
            usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="8765", master_code="4321", lock_admin_code="4321"
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode) as ctx:
            self._push(code, gateway)

        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, str(ctx.exception))

    def test_rejection_of_a_pin_not_matching_the_cached_admin_code_has_no_hint(self):
        gateway = FakeGateway(
            usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="8765", reject_pins={12: {"4321"}}
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode) as ctx:
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="reads back empty")
        self.assertNotIn("admin code", str(ctx.exception))
        self.assertNotIn("admin code", code.last_push_error)

    def test_a_different_code_in_the_slot_gets_no_admin_code_hint(self):
        # The slot holds something else, so the admin code isn't why our PIN isn't there.
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            admin_code="4321",
            get_responses=[{"userIdStatus": 1, "userCode": "9999"}],
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode) as ctx:
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="holds a different code")
        self.assertNotIn("admin code", str(ctx.exception))

    def test_one_empty_answer_then_silence_stays_pending_with_the_hint(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            admin_code="4321",
            get_responses=[{"userIdStatus": 0, "userCode": ""}, timeout, timeout],
        )
        code = self._make_code(pin="4321")

        # The sanitizer masks digit runs, so it's turned off here to check the
        # message the push builds, and the logs aren't sanitized at all.
        with (
            patch.object(lock_push_uc, "sanitize_push_error_for_storage", lambda message: message or ""),
            self.assertLogs("locks.use_cases.lock_push", level="DEBUG") as logs,
            self.assertRaises(LockUnreachable),
        ):
            self._push(code, gateway)

        code.refresh_from_db()
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.PENDING, 1))
        self.assertIn("LockCodeUnverified", code.last_push_error)
        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, assignment.last_push_error)
        [marker] = DoorCodeEvent.objects.filter(door_code=code, metadata__action=lock_push_uc._UNCONFIRMED_PUSH_ACTION)
        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, marker.metadata["reason"])
        for text in (assignment.last_push_error, marker.metadata["reason"], "\n".join(logs.output)):
            self.assertNotIn("4321", text)
        self.assertEqual(self._unconfirmed_slots(code), [1])

    def test_readback_timeouts_alone_get_no_admin_code_hint(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            admin_code="4321",
            get_responses=[timeout, timeout, timeout],
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)

        code.refresh_from_db()
        self.assertNotIn("admin code", code.last_push_error)

    def test_pin_different_from_admin_code_proceeds(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="8765")
        code = self._make_code(pin="4321")

        self._push(code, gateway)

        self.assertEqual(len(self._calls(gateway, "set")), 1)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_admin_code_not_exposed_proceeds_normally(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        exposed = [v.get("property") for v in gateway.node_get_defined_value_ids(node_id=12)]
        self.assertNotIn("adminCode", exposed)
        code = self._make_code(pin="4321")

        self._push(code, gateway)

        self.assertEqual(len(self._calls(gateway, "set")), 1)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_admin_code_exposed_but_empty_proceeds_normally(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="")
        code = self._make_code(pin="4321")

        self._push(code, gateway)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_scheduler_does_not_retry_rejected_code(self):
        from locks.tasks import push_pending_door_codes

        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321")
        code = self._make_code(pin="4321", push_state=DoorCode.PushState.PENDING)

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertIn("admin code", code.last_push_error)
        # First tick fails the lock terminally, the second tick skips the failed lock.
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.FAILED, 1))

    # Issue #125: the Supervision result of the CC 99 set.

    def test_supervision_fail_is_terminal_for_the_lock_without_a_readback(self):
        from types import SimpleNamespace

        fail_shapes = [
            {"status": 2},
            {"response": {"status": 2}},
            {"result": {"status": 2}},
            SimpleNamespace(status=2),
        ]
        for index, set_result in enumerate(fail_shapes):
            with self.subTest(set_result=set_result):
                pin = f"43{index:02d}"
                gateway = FakeGateway(
                    usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, set_result=set_result, reject_pins={12: {pin}}
                )
                code = self._make_code(pin=pin)

                with self.assertRaises(LockRejectedCode) as ctx:
                    self._push(code, gateway)

                self.assertIn("Supervision reported Fail", str(ctx.exception))
                self.assertNotIn("admin code", str(ctx.exception))
                # The lock said no, so nothing is read back or cleared.
                self.assertEqual([c["method_name"] for c in gateway.invoke_calls], ["set"])
                self._assert_terminal_failure(code, error_contains="Supervision reported Fail")
                failed = DoorCodeEvent.objects.get(
                    door_code=code, event_type=DoorCodeEvent.EventType.CODE_FAILED, metadata__action="push"
                )
                self.assertEqual(failed.lock_entity_id, self.LOCK_ENTITY_ID)
                self.assertEqual(
                    (failed.metadata.get("slot_index"), failed.metadata.get("supervision_status")), (1, "fail")
                )
                # Kept on record in case the lock stored it anyway, untagged, so only
                # a readback of this exact readable PIN counts the slot as ours.
                markers = list(
                    DoorCodeEvent.objects.filter(
                        door_code=code, metadata__action=lock_push_uc._UNCONFIRMED_PUSH_ACTION
                    ).values_list("lock_entity_id", "metadata")
                )
                self.assertEqual(len(markers), 1)
                lock_entity_id, metadata = markers[0]
                self.assertEqual((lock_entity_id, metadata["slot_index"]), (self.LOCK_ENTITY_ID, 1))
                self.assertNotIn(lock_push_uc._SLOT_VERIFIED_KEY, metadata)
                self.assertNotIn(lock_push_uc._SLOT_AVAILABLE_KEY, metadata)
                self.assertEqual(lock_push_uc._decrypt_expected_pin(metadata), pin)
                code.delete()

    def _supervision_fail(self, *, lock_stores_it: bool, **gateway_kwargs) -> tuple[DoorCode, FakeGateway]:
        """Push a code whose set comes back with Supervision Fail, the lock storing the PIN or not."""
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            set_result={"status": 2},
            reject_pins={} if lock_stores_it else {12: {"4321"}},
            cache_updates_on_set=True,
            **gateway_kwargs,
        )
        code = self._make_code(pin="4321")
        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)
        self.assertEqual(self._calls(gateway, "get"), [])
        gateway.invoke_calls.clear()
        gateway._set_result = None
        return code, gateway

    def test_supervision_fail_where_the_lock_stored_the_pin_anyway_is_cleared_by_a_delete(self):
        code, gateway = self._supervision_fail(lock_stores_it=True)
        self.assertEqual(gateway._lock_codes, {(12, 1): "4321"})

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._calls(gateway, "get")[0]["args"], [1])
        self.assertEqual(self._cleared_slots(gateway), [1])
        self.assertEqual(gateway._lock_codes, {})

    def test_supervision_fail_then_a_masked_keypad_code_in_the_slot_is_left_by_a_delete(self):
        code, gateway = self._supervision_fail(lock_stores_it=False)
        # Someone types a keypad code into slot 1 and the lock masks user codes.
        gateway._lock_codes[(12, 1)] = "9999"
        gateway._get_scripts = {None: [{"userIdStatus": 1, "userCode": "****"}]}

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(len(self._calls(gateway, "get")), 1)
        self.assertEqual(self._cleared_slots(gateway), [])
        self.assertEqual(gateway._lock_codes, {(12, 1): "9999"})

    def _retry(self, code: DoorCode, gateway: FakeGateway) -> DoorCode:
        admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        door_codes_uc.retry_push_door_code(code=code, actor_user=admin, zwavejs=gateway)
        code.refresh_from_db()
        return code

    def test_retry_after_a_supervision_fail_doesnt_adopt_or_resend_to_a_masked_slot(self):
        code, gateway = self._supervision_fail(lock_stores_it=False, drops_duplicates=False)
        gateway._reject_pins = {}
        gateway._lock_codes[(12, 1)] = "9999"
        gateway._slot_status[1] = 1
        gateway._get_scripts = {None: [{"userIdStatus": 1, "userCode": "****"}]}

        code = self._retry(code, gateway)

        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 2)
        self.assertEqual([c["args"][0] for c in self._calls(gateway, "set")], [2])
        self.assertEqual(gateway._lock_codes, {(12, 1): "9999", (12, 2): "4321"})
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertNotIn("adopted_existing_slot", synced.metadata)
        self.assertNotIn("resent_to_attempted_slot", synced.metadata)

    def test_retry_after_a_supervision_fail_where_the_slot_reads_back_empty_pushes_fresh(self):
        code, gateway = self._supervision_fail(lock_stores_it=False)
        gateway._reject_pins = {}

        code = self._retry(code, gateway)

        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual([c["args"][0] for c in self._calls(gateway, "set")], [1])
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertNotIn("adopted_existing_slot", synced.metadata)

    def test_retry_after_a_supervision_fail_adopts_only_a_readable_pin(self):
        # The lock stored the PIN despite the Fail and shows it, which is the one case adoption takes.
        code, gateway = self._supervision_fail(lock_stores_it=True)

        code = self._retry(code, gateway)

        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 1)
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertIs(synced.metadata.get("adopted_existing_slot"), True)

    def test_supervision_fail_with_a_cached_admin_code_match_says_it_may_match(self):
        gateway = FakeGateway(
            usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321", set_result={"status": 2}
        )
        code = self._make_code(pin="4321")

        with (
            self.assertLogs("locks.use_cases.lock_push", level="DEBUG") as logs,
            self.assertRaises(LockRejectedCode) as ctx,
        ):
            self._push(code, gateway)

        self.assertEqual(self._calls(gateway, "get"), [])
        self._assert_terminal_failure(code, error_contains="Supervision reported Fail")
        self._assert_admin_code_hint_without_the_code(code, ctx.exception, logs)

    def test_a_long_error_keeps_the_hint_whole_on_the_lock_and_drops_it_whole_from_the_rollup(self):
        # PR #200 review: a 500 character cut never lands inside the hint.
        hint = lock_push_uc._ADMIN_CODE_HINT
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321")
        code = self._make_code(pin="4321")
        rejection = LockRejectedCode(f"Lock did not store the code {'x' * 480}", clear_slot=True)

        with (
            patch.object(lock_push_uc, "_verify_user_code_slot", side_effect=rejection),
            self.assertRaises(LockRejectedCode),
        ):
            self._push(code, gateway)

        code.refresh_from_db()
        lock_error = DoorCodeLockAssignment.objects.get(door_code=code).last_push_error
        self.assertEqual(len(lock_error), 500)
        self.assertTrue(lock_error.endswith(f"x {hint}"))
        self.assertEqual(lock_push_uc.strip_admin_code_hint(lock_error), lock_error[: -len(hint) - 1])
        # The rollup adds "lock.back_door: " in front, so the hint doesn't fit and goes whole.
        self.assertTrue(code.last_push_error.startswith(f"{self.LOCK_ENTITY_ID}: Lock did not store the code x"))
        self.assertLessEqual(len(code.last_push_error), 500)
        self.assertTrue(code.last_push_error.endswith("x"))
        self.assertNotIn("This PIN", code.last_push_error)

    def test_cut_push_error_never_cuts_inside_the_hint(self):
        hint = lock_push_uc._ADMIN_CODE_HINT
        cut = lock_push_uc._cut_push_error
        fits = f"{'x' * (499 - len(hint))} {hint}"
        self.assertEqual(len(fits), 500)
        self.assertEqual(cut(fits), fits)
        self.assertEqual(cut(f"{fits}; lock.b: timeout"), fits)
        # One character more and the hint would end past 500, so it goes with its space.
        crossing = f"{'x' * (500 - len(hint))} {hint}"
        self.assertEqual(cut(crossing), "x" * (500 - len(hint)))
        # A hint that starts at 500 or later is past the cut anyway.
        self.assertEqual(cut(f"{'x' * 500} {hint}"), "x" * 500)
        self.assertEqual(cut("x" * 600), "x" * 500)

    # Issue #124: the node's value IDs are fetched once per push and shared.

    def test_a_fresh_push_fetches_the_value_ids_once(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="8765")
        code = self._make_code(pin="4321")

        self._push(code, gateway)

        self.assertEqual(gateway.value_id_fetches, 1)

    def test_an_empty_readback_with_the_admin_code_hint_fetches_the_value_ids_once(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321")
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode) as ctx:
            self._push(code, gateway)

        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, str(ctx.exception))
        self.assertEqual(gateway.value_id_fetches, 1)

    def test_a_supervision_fail_with_the_admin_code_hint_fetches_the_value_ids_once(self):
        gateway = FakeGateway(
            usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321", set_result={"status": 2}
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode) as ctx:
            self._push(code, gateway)

        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, str(ctx.exception))
        self.assertEqual(gateway.value_id_fetches, 1)

    def test_one_empty_answer_then_silence_with_the_hint_fetches_the_value_ids_once(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            admin_code="4321",
            get_responses=[{"userIdStatus": 0, "userCode": ""}, timeout, timeout],
        )
        code = self._make_code(pin="4321")

        with (
            patch.object(lock_push_uc, "sanitize_push_error_for_storage", lambda message: message or ""),
            self.assertRaises(LockUnreachable),
        ):
            self._push(code, gateway)

        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, DoorCodeLockAssignment.objects.get(door_code=code).last_push_error)
        self.assertEqual(gateway.value_id_fetches, 1)

    def test_an_adopted_slot_doesnt_fetch_the_value_ids(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, get_responses=[timeout, timeout, timeout])
        code = self._make_code(pin="4321")
        with self.assertRaises(LockUnreachable):
            self._push(code, gateway)
        gateway.value_id_fetches = 0

        result = self._push(code, gateway)

        self.assertEqual(result.slot_index, 1)
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertIs(synced.metadata.get("adopted_existing_slot"), True)
        self.assertEqual(gateway.value_id_fetches, 0)

    def test_supervision_fail_on_one_lock_doesnt_stop_another(self):
        class FailsOnSide(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                result = super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )
                if command_class == 99 and method_name == "set" and node_id == 13:
                    return {"status": 2}
                return result

        Entity.objects.create(
            entity_id="lock.side_door",
            domain="lock",
            name="Side Door",
            attributes={"zwavejs": {"node_id": 13}},
            source="home_assistant",
        )
        gateway = FailsOnSide(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, reject_pins={13: {"4321"}})
        code = self._make_code(pin="4321")
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id="lock.side_door")

        successes, failures = push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway)

        self.assertEqual([s.lock_entity_id for s in successes], [self.LOCK_ENTITY_ID])
        self.assertEqual([lock for lock, _reason in failures], ["lock.side_door"])
        back = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        side = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id="lock.side_door")
        self.assertEqual((back.slot_index, back.push_state), (1, DoorCode.PushState.PUSHED))
        self.assertEqual(
            (side.slot_index, side.push_state, side.push_attempt_count), (None, DoorCode.PushState.FAILED, 1)
        )
        self.assertIn("Supervision reported Fail", side.last_push_error)
        # The rollup: failed, with the lock that failed in the error.
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertIn("lock.side_door", code.last_push_error)
        self.assertEqual([c["node_id"] for c in self._calls(gateway, "get")], [12])

    def test_supervision_success_still_reads_back(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, set_result={"status": 255})
        code = self._make_code(pin="4321")

        self._push(code, gateway)

        self.assertEqual([c["method_name"] for c in gateway.invoke_calls], ["set", "get"])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_supervision_success_with_an_empty_readback_is_still_rejected(self):
        # A lock can report Success and still drop the code.
        gateway = FakeGateway(
            usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, set_result={"status": 255}, reject_pins={12: {"4321"}}
        )
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="slot 1 reads back empty")
        self.assertEqual(len(self._calls(gateway, "get")), 2)
        self.assertEqual(self._cleared_slots(gateway), [1])

    def test_supervision_success_with_a_masked_readback_is_accepted_like_before(self):
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            set_result={"status": 255},
            get_responses=[{"userIdStatus": 1, "userCode": "****"}],
        )
        code = self._make_code(pin="4321")

        with self.assertLogs("locks.use_cases.lock_push", level="WARNING") as logs:
            self._push(code, gateway)

        self.assertIn("masked or unreadable", "\n".join(logs.output))
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_no_usable_supervision_result_reads_back_like_before(self):
        # Unsupervised (nothing back), NoSupport, Working, and shapes that aren't a Supervision result.
        no_verdict = [
            None,
            {},
            {"status": 0},
            {"status": 1, "remainingDuration": {"value": 1, "unit": "seconds"}},
            {"status": "fail"},
            # A status has to be a real int; a numeric string isn't a Supervision result.
            {"status": "2"},
            {"response": {"status": "2"}},
            {"status": 2.0},
            {"status": True},
            {"userIdStatus": 2},
            2,
            "2",
            True,
            [{"status": 2}],
        ]
        for index, set_result in enumerate(no_verdict):
            with self.subTest(set_result=set_result):
                pin = f"43{index:02d}"
                gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, set_result=set_result)
                code = self._make_code(pin=pin)

                self._push(code, gateway)

                self.assertEqual([c["method_name"] for c in gateway.invoke_calls], ["set", "get"])
                code.refresh_from_db()
                self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
                code.delete()

    def test_no_supervision_result_and_an_empty_readback_is_rejected_like_before(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, reject_pins={12: {"4321"}})
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode):
            self._push(code, gateway)

        self._assert_terminal_failure(code, error_contains="slot 1 reads back empty")
        self.assertEqual(len(self._calls(gateway, "get")), 2)


class MultiLockAndAdoptionTests(EncryptionTestMixin, TestCase):
    """Issue #107 review: shared-row aggregation across locks, and adopting a slot that already holds the PIN."""

    BACK = "lock.back_door"  # node 12
    SIDE = "lock.side_door"  # node 13

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        for entity_id, name, node_id in ((self.BACK, "Back Door", 12), (self.SIDE, "Side Door", 13)):
            Entity.objects.create(
                entity_id=entity_id,
                domain="lock",
                name=name,
                attributes={"zwavejs": {"node_id": node_id}},
                source="home_assistant",
            )
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_code(self, *, pin: str, lock_entity_ids: list[str], **kwargs) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            **kwargs,
        )
        for lock_entity_id in lock_entity_ids:
            DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=lock_entity_id)
        return code

    @staticmethod
    def _set_nodes(gateway: FakeGateway) -> list[int]:
        return [c["node_id"] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "set"]

    def _slot(self, code: DoorCode, lock_entity_id: str) -> int | None:
        return DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=lock_entity_id).slot_index

    def _assert_rejection_kept(self, code: DoorCode) -> None:
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertIn("reads back empty", code.last_push_error)
        self.assertIsNone(self._slot(code, self.BACK))
        self.assertEqual(self._slot(code, self.SIDE), 1)

    def test_rejection_on_first_lock_is_not_hidden_by_success_on_second(self):
        from locks.use_cases.lock_push import push_door_code_to_assigned_locks

        gateway = FakeGateway(usersNumber=3, reject_pins={12: {"4321"}})
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK, self.SIDE])

        successes, failures = push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway)

        self.assertEqual(self._set_nodes(gateway), [12, 13])
        self.assertEqual((len(successes), len(failures)), (1, 1))
        self._assert_rejection_kept(code)

    def test_rejection_on_second_lock_after_success_on_first(self):
        from locks.use_cases.lock_push import push_door_code_to_assigned_locks

        gateway = FakeGateway(usersNumber=3, reject_pins={12: {"4321"}})
        code = self._make_code(pin="4321", lock_entity_ids=[self.SIDE, self.BACK])

        push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway)

        self.assertEqual(self._set_nodes(gateway), [13, 12])
        self._assert_rejection_kept(code)

    def test_transient_failure_on_one_lock_stays_pending_and_scheduler_retries_it(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        from locks.tasks import push_pending_door_codes
        from locks.use_cases.lock_push import push_door_code_to_assigned_locks

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(
            usersNumber=3,
            get_responses={13: [timeout, timeout, timeout]},
            cache_updates_on_set=False,
        )
        code = self._make_code(pin="4321", lock_entity_ids=[self.SIDE, self.BACK])

        push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn("LockCodeUnverified", code.last_push_error)
        self.assertIsNone(self._slot(code, self.SIDE))
        self.assertEqual(self._slot(code, self.BACK), 1)

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")
        self.assertEqual(self._slot(code, self.SIDE), 1)
        # Only the side lock was retried, and since its first set did land it was
        # adopted from the recorded attempt instead of written again.
        self.assertEqual(self._set_nodes(gateway), [13, 12])

    def test_scheduler_retry_adopts_slot_where_unverified_code_landed(self):
        # All readbacks time out, but the code did land in slot 1. The retry must
        # adopt slot 1 (recorded by the failed attempt) instead of writing slot 2,
        # which the lock would drop as a duplicate, orphaning slot 1. Adoption goes
        # off the recorded attempt and the readback, not the value cache, which
        # stays stale here.
        from integrations_zwavejs.manager import ZwavejsCommandError

        from locks.tasks import push_pending_door_codes

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(
            usersNumber=3,
            get_responses=[timeout, timeout, timeout],
            cache_updates_on_set=False,
        )
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK], days_of_week=0b1)

        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIsNone(self._slot(code, self.BACK))
        # The readback never answered, so no schedule went out for that attempt.
        self.assertEqual([c for c in gateway.invoke_calls if c["command_class"] == 78], [])

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._slot(code, self.BACK), 1)
        # No second set: the existing slot was verified and adopted, then the schedule pushed to it.
        self.assertEqual(self._set_nodes(gateway), [12])
        schedule_calls = [c for c in gateway.invoke_calls if c["command_class"] == 78]
        self.assertEqual(len(schedule_calls), 1)
        self.assertEqual(schedule_calls[0]["args"][0]["userId"], 1)
        synced = DoorCodeEvent.objects.get(
            door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED, metadata__action="pushed"
        )
        self.assertEqual(synced.metadata.get("slot_index"), 1)
        self.assertIs(synced.metadata.get("adopted_existing_slot"), True)

    @staticmethod
    def _keypad_code_in_slot_3(gateway: FakeGateway) -> None:
        # Entered on the lock's keypad: on the lock and in the cache, no assignment anywhere.
        gateway._lock_codes[(12, 3)] = "4321"
        gateway._cache_codes[(12, 3)] = "4321"

    @staticmethod
    def _slot_calls(gateway: FakeGateway, slot_index: int) -> list[dict]:
        return [
            c
            for c in gateway.invoke_calls
            if (c["command_class"] == 99 and c["args"] and c["args"][0] == slot_index)
            or (c["command_class"] == 78 and c["args"][0].get("userId") == slot_index)
        ]

    @staticmethod
    def _record_attempt(code: DoorCode, lock_entity_id: str, slot_index: int) -> None:
        DoorCodeEvent.objects.create(
            door_code=code,
            lock_entity_id=lock_entity_id,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={"action": lock_push_uc._UNCONFIRMED_PUSH_ACTION, "slot_index": slot_index},
        )

    def test_keypad_code_with_same_pin_is_not_adopted(self):
        gateway = FakeGateway(usersNumber=3, drops_duplicates=False)
        self._keypad_code_in_slot_3(gateway)
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK], days_of_week=0b1)

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        # Normal push to the lowest free slot; slot 3 is never read, written, cleared or scheduled.
        self.assertEqual(result.slot_index, 1)
        self.assertEqual(self._set_nodes(gateway), [12])
        self.assertEqual(self._slot_calls(gateway, 3), [])
        self.assertEqual(gateway._lock_codes[(12, 3)], "4321")
        synced = DoorCodeEvent.objects.get(
            door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED, metadata__action="pushed"
        )
        self.assertNotIn("adopted_existing_slot", synced.metadata)

    def test_keypad_code_with_same_pin_on_a_yale_fails_without_touching_slot_3(self):
        # A Yale drops the duplicate, so the push fails, but the keypad user's slot is left alone.
        gateway = FakeGateway(usersNumber=3)
        self._keypad_code_in_slot_3(gateway)
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK])

        with self.assertRaises(LockRejectedCode):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        self.assertEqual(self._set_nodes(gateway), [12])
        self.assertEqual(self._slot_calls(gateway, 3), [])
        self.assertEqual(gateway._lock_codes[(12, 3)], "4321")
        self.assertIsNone(self._slot(code, self.BACK))

    def test_prior_attempt_on_a_different_slot_is_not_adopted(self):
        gateway = FakeGateway(usersNumber=3, drops_duplicates=False)
        self._keypad_code_in_slot_3(gateway)
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK])
        self._record_attempt(code, self.BACK, 2)

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        # Slot 2 was checked (reads back empty) and skipped; slot 3 was never considered.
        self.assertEqual(result.slot_index, 1)
        self.assertEqual(self._set_nodes(gateway), [12])
        self.assertEqual(self._slot_calls(gateway, 3), [])
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
        self.assertNotIn("adopted_existing_slot", synced.metadata)

    def test_prior_attempt_on_a_different_lock_is_not_adopted(self):
        gateway = FakeGateway(usersNumber=3, drops_duplicates=False)
        self._keypad_code_in_slot_3(gateway)
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK])
        self._record_attempt(code, self.SIDE, 3)

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        self.assertEqual(result.slot_index, 1)
        self.assertEqual(self._slot_calls(gateway, 3), [])
        self.assertEqual(self._set_nodes(gateway), [12])

    def test_attempt_recorded_before_a_later_success_is_not_adopted(self):
        gateway = FakeGateway(usersNumber=3, drops_duplicates=False)
        gateway._lock_codes[(12, 1)] = "4321"
        gateway._cache_codes[(12, 1)] = "4321"
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK])
        self._record_attempt(code, self.BACK, 1)
        DoorCodeEvent.objects.create(
            door_code=code,
            lock_entity_id=self.BACK,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata={"action": "pushed", "slot_index": 1},
        )

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        # Slot 1 belongs to an earlier, finished push cycle: never read back or adopted.
        self.assertEqual(result.slot_index, 2)
        self.assertEqual(self._slot_calls(gateway, 1), [])
        latest = DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED).latest(
            "id"
        )
        self.assertNotIn("adopted_existing_slot", latest.metadata)

    def test_adoption_skips_recorded_slot_now_held_by_another_assignment(self):
        code = self._make_code(pin="4321", lock_entity_ids=[self.BACK])
        self._record_attempt(code, self.BACK, 1)
        other = self._make_code(pin="4321", lock_entity_ids=[])
        DoorCodeLockAssignment.objects.create(door_code=other, lock_entity_id=self.BACK, slot_index=1)
        gateway = FakeGateway(usersNumber=3)
        gateway._lock_codes[(12, 1)] = "4321"

        with self.assertRaises(LockRejectedCode):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.BACK, zwavejs=gateway)

        # Slot 1 stays with the other code and is never read; the duplicate written to slot 2 was dropped.
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=other).slot_index, 1)
        self.assertIsNone(self._slot(code, self.BACK))
        self.assertEqual([c for c in gateway.invoke_calls if c["args"] and c["args"][0] == 1], [])


class UnconfirmedSlotCleanupTests(EncryptionTestMixin, TestCase):
    """Delete / deactivate / PIN change of a code whose push landed but was never confirmed.

    The slot is only known from the ``push_unconfirmed`` event, so it has to be
    read back and cleared if it holds the code's old PIN.
    """

    LOCK = "lock.back_door"  # node 12
    PIN = "4321"

    # Readback the cleanup sees -> whether the slot should be cleared.
    READBACKS = {
        "old pin": ([], True),
        "old pin disabled": ([{"userIdStatus": 2, "userCode": "4321"}], True),
        "different code": ([{"userIdStatus": 1, "userCode": "9999"}], False),
        # The slot was Available when the push picked it and nothing else claims it (issue #152).
        "masked": ([{"userIdStatus": 1, "userCode": "****"}], True),
        "empty": ([{"userIdStatus": 0, "userCode": ""}, {"userIdStatus": 0, "userCode": ""}], False),
    }

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK,
            domain="lock",
            name="Back Door",
            attributes={"zwavejs": {"node_id": 12}},
            source="home_assistant",
        )
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _pending_unconfirmed(self, cleanup_readback: list) -> tuple[DoorCode, FakeGateway, int]:
        """Push a code whose set lands but whose readbacks all time out, then script the cleanup readback."""
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(usersNumber=5, get_responses=[timeout, timeout, timeout])
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK)
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK, zwavejs=gateway)

        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=code).slot_index)
        slot = lock_push_uc._unconfirmed_attempt_slots(door_code=code, lock_entity_id=self.LOCK)[0]
        self.assertEqual(gateway._lock_codes[(12, slot)], self.PIN)
        gateway._get_scripts = {None: list(cleanup_readback)}
        gateway.invoke_calls.clear()
        return code, gateway, slot

    @staticmethod
    def _cleared(gateway: FakeGateway) -> list[int]:
        return [c["args"][0] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "clear"]

    def _check(self, operation) -> None:
        for name, (readback, should_clear) in self.READBACKS.items():
            with self.subTest(readback=name):
                code, gateway, slot = self._pending_unconfirmed(readback)

                operation(code, gateway)

                if should_clear:
                    self.assertEqual(self._cleared(gateway), [slot])
                    # The old PIN is gone (a PIN change may then reuse the slot for the new PIN).
                    self.assertNotEqual(gateway._lock_codes.get((12, slot)), self.PIN)
                else:
                    self.assertNotIn(slot, self._cleared(gateway))

    def test_delete_clears_unconfirmed_slot_holding_the_pin(self):
        def delete(code, gateway):
            door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)
            self.assertFalse(DoorCode.objects.filter(id=code.id).exists())

        self._check(delete)

    def test_delete_records_cleared_unconfirmed_slot(self):
        code, gateway, slot = self._pending_unconfirmed([])

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        deleted = DoorCodeEvent.objects.get(event_type=DoorCodeEvent.EventType.CODE_DELETED)
        self.assertEqual(
            deleted.metadata["cleared_unconfirmed_slots"], [{"lock_entity_id": self.LOCK, "slot_index": slot}]
        )

    def test_deactivate_clears_unconfirmed_slot_holding_the_pin(self):
        def deactivate(code, gateway):
            door_codes_uc.update_door_code(
                code=code, changes={"is_active": False}, actor_user=self.user, zwavejs=gateway
            )
            # Deactivation never re-pushes.
            self.assertEqual([c for c in gateway.invoke_calls if c["method_name"] == "set"], [])

        self._check(deactivate)

    def test_pin_change_clears_unconfirmed_slot_holding_the_old_pin(self):
        def change_pin(code, gateway):
            door_codes_uc.update_door_code(code=code, changes={"code": "5555"}, actor_user=self.user, zwavejs=gateway)
            # The new PIN still gets pushed afterwards.
            sets = [c for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "set"]
            self.assertEqual([c["args"][2] for c in sets], ["5555"])

        self._check(change_pin)

    def test_dropping_the_lock_clears_unconfirmed_slot_holding_the_pin(self):
        code, gateway, slot = self._pending_unconfirmed([])

        door_codes_uc.update_door_code(
            code=code, changes={"lock_entity_ids": []}, actor_user=self.user, zwavejs=gateway
        )

        self.assertEqual(self._cleared(gateway), [slot])

    def test_schedule_only_change_adopts_instead_of_clearing(self):
        code, gateway, slot = self._pending_unconfirmed([])

        door_codes_uc.update_door_code(code=code, changes={"days_of_week": 0b1}, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(self._cleared(gateway), [])
        self.assertEqual([c for c in gateway.invoke_calls if c["method_name"] == "set"], [])
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, slot)

    def test_slot_held_by_another_assignment_is_not_touched(self):
        code, gateway, slot = self._pending_unconfirmed([])
        other = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("9999"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=other, lock_entity_id=self.LOCK, slot_index=slot)

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual([c for c in gateway.invoke_calls if c["args"] and c["args"][0] == slot], [])

    def test_cleanup_failure_is_logged_and_refuses_the_delete(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        code, gateway, slot = self._pending_unconfirmed([])
        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway._get_scripts = {None: [timeout, timeout, timeout]}

        with (
            self.assertLogs("locks.use_cases.lock_push", level="WARNING") as logs,
            self.assertRaises(door_codes_uc.SlotClearFailed),
        ):
            door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertIn(f"unconfirmed slot {slot}", "\n".join(logs.output))
        self.assertEqual(self._cleared(gateway), [])
        self.assertTrue(DoorCode.objects.filter(id=code.id).exists())

    def _pin_change_while_the_cleanup_times_out(self) -> tuple[DoorCode, FakeGateway, int]:
        """Issue #144 review: 4321 sits in an unconfirmed slot, then the PIN changes while its cleanup times out."""
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        code, gateway, slot = self._pending_unconfirmed([timeout, timeout, timeout])
        gateway.deliver_late_reports()  # the value cache catches up with the set

        door_codes_uc.update_door_code(code=code, changes={"code": "5555"}, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        lock = {s: c for (n, s), c in gateway._lock_codes.items() if n == 12}
        self.assertEqual(lock[slot], self.PIN)
        self.assertIn("5555", lock.values())
        self.assertNotEqual(code.push_state, DoorCode.PushState.PUSHED)
        return code, gateway, slot

    def test_old_pin_in_an_unconfirmed_slot_is_cleared_after_a_pin_change_whose_cleanup_timed_out(self):
        code, gateway, slot = self._pin_change_while_the_cleanup_times_out()

        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        lock = {s: c for (n, s), c in gateway._lock_codes.items() if n == 12}
        self.assertNotIn(slot, lock)
        self.assertEqual(list(lock.values()), ["5555"])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_delete_after_a_pin_change_whose_cleanup_timed_out_clears_the_old_pin(self):
        code, gateway, slot = self._pin_change_while_the_cleanup_times_out()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual({s: c for (n, s), c in gateway._lock_codes.items() if n == 12}, {})

    def test_expected_pins_are_stored_encrypted(self):
        code, gateway, slot = self._pin_change_while_the_cleanup_times_out()

        for event in DoorCodeEvent.objects.filter(
            door_code=code, metadata__action__in=["push_unconfirmed", "clear_failed"]
        ):
            self.assertNotIn(self.PIN, json.dumps(event.metadata))
            self.assertNotIn("5555", json.dumps(event.metadata))
            self.assertIn(SettingsEncryption.get().decrypt(event.metadata["encrypted_pin"]), {self.PIN, "5555"})

    def test_unconfirmed_cleanup_compares_against_the_pin_that_attempt_sent(self):
        # The attempt sent 4321, but the code's PIN is 5555 by the time it's deleted.
        code, gateway, slot = self._pending_unconfirmed([])
        DoorCode.objects.filter(id=code.id).update(encrypted_pin=SettingsEncryption.get().encrypt("5555"))
        code.refresh_from_db()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(self._cleared(gateway), [slot])
        self.assertNotIn((12, slot), gateway._lock_codes)

    def _backdate_events_and_run_retention(self, code: DoorCode, days: int = 91) -> None:
        from django.utils import timezone

        from alarm.models import SystemConfig
        from locks.tasks import cleanup_door_code_events

        SystemConfig.objects.update_or_create(
            key="door_code_events.retention_days",
            defaults={"name": "Door code event retention (days)", "value_type": "integer", "value": 90},
        )
        DoorCodeEvent.objects.filter(door_code=code).update(created_at=timezone.now() - timedelta(days=days))
        cleanup_door_code_events()

    def test_retention_keeps_unresolved_markers(self):
        code, gateway, slot = self._pin_change_while_the_cleanup_times_out()

        self._backdate_events_and_run_retention(code)

        # Only the unresolved marker survives; the closed push_unconfirmed window and
        # everything else ages out.
        remaining = DoorCodeEvent.objects.filter(door_code=code)
        self.assertEqual(
            [(e.metadata.get("action"), e.metadata.get("slot_index")) for e in remaining], [("clear_failed", slot)]
        )
        # The marker still drives the retry, so the old PIN still goes.
        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()
        self.assertNotIn((12, slot), gateway._lock_codes)

    def test_retention_keeps_unsettled_unconfirmed_attempts_and_prunes_settled_ones(self):
        code, gateway, slot = self._pending_unconfirmed([])
        attempt = DoorCodeEvent.objects.get(door_code=code, metadata__action="push_unconfirmed")

        self._backdate_events_and_run_retention(code)

        # Still in its window and nothing has checked the slot, so it stays.
        self.assertEqual(list(DoorCodeEvent.objects.filter(door_code=code).values_list("id", flat=True)), [attempt.id])

        # Issue #161: the deactivate clears the slot, which settles the attempt, so
        # it and its marker age out even though no push closed the window.
        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user, zwavejs=gateway)
        self.assertEqual(self._cleared(gateway), [slot])
        self._backdate_events_and_run_retention(code)
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=code).exists())

    def _deactivate_while_the_cleanup_times_out(self) -> tuple[DoorCode, FakeGateway, int]:
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        code, gateway, slot = self._pending_unconfirmed([timeout, timeout, timeout])

        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertEqual(gateway._lock_codes[(12, slot)], self.PIN)
        self.assertFalse(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot {slot} on {self.LOCK}", code.last_push_error)
        updated = DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_UPDATED).latest("id")
        self.assertEqual(
            [(f["lock_entity_id"], f["slot_index"]) for f in updated.metadata["failed_slot_clears"]],
            [(self.LOCK, slot)],
        )
        gateway.invoke_calls.clear()
        return code, gateway, slot

    def test_deactivating_while_the_cleanup_times_out_is_not_marked_pushed(self):
        code, gateway, slot = self._deactivate_while_the_cleanup_times_out()
        failed = DoorCodeEvent.objects.get(door_code=code, metadata__action="clear_failed")
        self.assertEqual((failed.lock_entity_id, failed.metadata["slot_index"]), (self.LOCK, slot))
        self.assertTrue(failed.metadata["unconfirmed"])

        # The scheduler checks the slot again once the lock answers and clears it.
        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            self.assertEqual(push_pending_door_codes(), 1)

        code.refresh_from_db()
        self.assertEqual(self._cleared(gateway), [slot])
        self.assertNotIn((12, slot), gateway._lock_codes)
        self.assertEqual([c for c in gateway.invoke_calls if c["method_name"] == "set"], [])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_saving_an_inactive_code_as_off_again_reruns_the_unconfirmed_cleanup(self):
        code, gateway, slot = self._deactivate_while_the_cleanup_times_out()

        # is_active=false is unchanged, but the unconfirmed slot may still hold the PIN.
        door_codes_uc.update_door_code(code=code, changes={"is_active": False}, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertEqual(self._cleared(gateway), [slot])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")

    def _deleted_event(self) -> DoorCodeEvent:
        return DoorCodeEvent.objects.get(event_type=DoorCodeEvent.EventType.CODE_DELETED)

    def test_delete_checks_an_unconfirmed_slot_on_a_lock_the_code_was_dropped_from(self):
        # Issue #134: the lock was dropped without its cleanup running (a save with no
        # gateway, or one from before #111), so only the push_unconfirmed event points at it.
        code, gateway, slot = self._pending_unconfirmed([])
        door_codes_uc.update_door_code(code=code, changes={"lock_entity_ids": []}, actor_user=self.user)
        self.assertFalse(DoorCodeLockAssignment.objects.filter(door_code=code).exists())

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._cleared(gateway), [slot])
        self.assertNotIn((12, slot), gateway._lock_codes)
        self.assertEqual(
            self._deleted_event().metadata["cleared_unconfirmed_slots"],
            [{"lock_entity_id": self.LOCK, "slot_index": slot}],
        )

    def test_delete_refuses_while_an_unconfirmed_slot_on_a_dropped_lock_cant_be_checked(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        code, gateway, slot = self._pending_unconfirmed([timeout, timeout, timeout])
        door_codes_uc.update_door_code(code=code, changes={"lock_entity_ids": []}, actor_user=self.user)

        with self.assertRaises(door_codes_uc.SlotClearFailed):
            door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertTrue(DoorCode.objects.filter(id=code.id).exists())
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertEqual((failure.lock_entity_id, failure.slot_index, failure.unconfirmed), (self.LOCK, slot, True))

    def test_delete_keeps_a_trace_of_unconfirmed_slots_on_a_lock_that_is_gone(self):
        code, gateway, slot = self._pending_unconfirmed([])
        Entity.objects.filter(entity_id=self.LOCK).delete()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(gateway.invoke_calls, [])
        metadata = self._deleted_event().metadata
        [unchecked] = metadata["unconfirmed_slots_unchecked"]
        self.assertEqual(
            (unchecked["lock_entity_id"], unchecked["slot_index"], unchecked["permanent"]), (self.LOCK, slot, True)
        )
        self.assertIn("NotFound", unchecked["reason"])
        self.assertNotIn("cleared_unconfirmed_slots", metadata)

    def test_synced_code_delete_keeps_a_trace_of_unconfirmed_slots_it_couldnt_check(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        code, gateway, slot = self._pending_unconfirmed([timeout, timeout, timeout])
        DoorCode.objects.filter(id=code.id).update(source=DoorCode.Source.SYNCED)
        code.refresh_from_db()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        [unchecked] = self._deleted_event().metadata["unconfirmed_slots_unchecked"]
        self.assertEqual((unchecked["lock_entity_id"], unchecked["slot_index"]), (self.LOCK, slot))
        self.assertNotIn("permanent", unchecked)

    def test_dropping_a_lock_that_is_gone_records_its_unconfirmed_slot_in_the_update_event(self):
        code, gateway, slot = self._pending_unconfirmed([])
        Entity.objects.filter(entity_id=self.LOCK).delete()

        door_codes_uc.update_door_code(
            code=code, changes={"lock_entity_ids": []}, actor_user=self.user, zwavejs=gateway
        )

        updated = DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_UPDATED).latest("id")
        [failure] = updated.metadata["failed_slot_clears"]
        self.assertEqual(
            (failure["lock_entity_id"], failure["slot_index"], failure["permanent"]), (self.LOCK, slot, True)
        )


class LockListChangeTests(EncryptionTestMixin, TestCase):
    """Issue #133: changing a code's locks keeps the slots of the locks that stay."""

    BACK = "lock.back_door"  # node 12
    SIDE = "lock.side_door"  # node 13
    FRONT = "lock.front_door"  # node 14
    PIN = "4321"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        for entity_id, name, node_id in (
            (self.BACK, "Back Door", 12),
            (self.SIDE, "Side Door", 13),
            (self.FRONT, "Front Door", 14),
        ):
            Entity.objects.create(
                entity_id=entity_id,
                domain="lock",
                name=name,
                attributes={"zwavejs": {"node_id": node_id}},
                source="home_assistant",
            )
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _pushed_code(self, lock_entity_ids: list[str], **gateway_kwargs) -> tuple[DoorCode, FakeGateway]:
        """Create and push a code, with the cache seeing each set like it does after the readback get."""
        gateway = FakeGateway(usersNumber=5, cache_updates_on_set=True, **gateway_kwargs)
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            lock_entity_ids=lock_entity_ids,
            actor_user=self.user,
            zwavejs=gateway,
        )
        gateway.invoke_calls.clear()
        return code, gateway

    def _update(self, code: DoorCode, gateway: FakeGateway, changes: dict) -> DoorCode:
        code = door_codes_uc.get_door_code_for_read(code_id=code.id)
        door_codes_uc.update_door_code(code=code, changes=changes, actor_user=self.user, zwavejs=gateway)
        return DoorCode.objects.get(id=code.id)

    @staticmethod
    def _calls(gateway: FakeGateway, method_name: str) -> list[tuple[int, list]]:
        return [
            (c["node_id"], c["args"])
            for c in gateway.invoke_calls
            if c["command_class"] == 99 and c["method_name"] == method_name
        ]

    @staticmethod
    def _lock_codes(gateway: FakeGateway, node_id: int) -> dict[int, str]:
        return {slot: pin for (node, slot), pin in gateway._lock_codes.items() if node == node_id}

    def _slots(self, code: DoorCode) -> dict[str, int | None]:
        return dict(DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", "slot_index"))

    def _updated_event(self, code: DoorCode) -> DoorCodeEvent:
        return DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_UPDATED).latest(
            "id"
        )

    def test_dropping_a_lock_keeps_the_kept_locks_slot(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        metadata = self._updated_event(code).metadata
        self.assertIn("lock_entity_ids", metadata["updated_fields"])
        self.assertEqual(metadata["removed_lock_entity_ids"], [self.SIDE])
        self.assertNotIn("added_lock_entity_ids", metadata)

    def test_dropping_a_lock_from_the_edit_form_keeps_one_slot_on_the_kept_lock(self):
        # The edit form always sends is_active. Unchanged, it doesn't re-push the kept lock (issue #139).
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"is_active": True, "lock_entity_ids": [self.BACK]})

        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_adding_a_lock_only_pushes_the_new_lock(self):
        code, gateway = self._pushed_code([self.BACK])

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK, self.SIDE]})

        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(self._calls(gateway, "set"), [(13, [1, 1, self.PIN])])
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        metadata = self._updated_event(code).metadata
        self.assertEqual(metadata["added_lock_entity_ids"], [self.SIDE])
        self.assertNotIn("removed_lock_entity_ids", metadata)

    def test_swapping_a_lock_clears_the_old_one_and_pushes_the_new_one(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK, self.FRONT]})

        self.assertEqual(self._slots(code), {self.BACK: 1, self.FRONT: 1})
        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [(14, [1, 1, self.PIN])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._lock_codes(gateway, 14), {1: self.PIN})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        metadata = self._updated_event(code).metadata
        self.assertEqual(metadata["added_lock_entity_ids"], [self.FRONT])
        self.assertEqual(metadata["removed_lock_entity_ids"], [self.SIDE])

    def test_unchanged_lock_list_with_a_label_edit_leaves_the_locks_alone(self):
        # The edit form always sends the lock list, so this is every label edit.
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"label": "Cleaner", "lock_entity_ids": [self.SIDE, self.BACK]})

        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(gateway.invoke_calls, [])
        metadata = self._updated_event(code).metadata
        self.assertNotIn("added_lock_entity_ids", metadata)
        self.assertNotIn("removed_lock_entity_ids", metadata)

    def test_pin_change_with_a_lock_change_moves_the_kept_lock_to_the_new_pin(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"code": "5555", "lock_entity_ids": [self.BACK, self.FRONT]})

        self.assertEqual(self._slots(code), {self.BACK: 1, self.FRONT: 1})
        self.assertCountEqual(self._calls(gateway, "clear"), [(13, [1]), (12, [1])])
        self.assertCountEqual(self._calls(gateway, "set"), [(12, [1, 1, "5555"]), (14, [1, 1, "5555"])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: "5555"})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._lock_codes(gateway, 14), {1: "5555"})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_deactivating_with_a_lock_change_clears_every_lock_without_pushing(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"is_active": False, "lock_entity_ids": [self.BACK, self.FRONT]})

        self.assertEqual(self._slots(code), {self.BACK: None, self.FRONT: None})
        self.assertCountEqual(self._calls(gateway, "clear"), [(13, [1]), (12, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        for node_id in (12, 13, 14):
            self.assertEqual(self._lock_codes(gateway, node_id), {})

    def test_dropping_the_lock_that_failed_marks_the_code_pushed(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE], reject_pins={13: {self.PIN}})
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")

    def test_dropping_every_lock_resets_a_failed_code(self):
        # Issue #142: the failure belonged to a lock the code isn't on any more.
        code, gateway = self._pushed_code([self.BACK], reject_pins={12: {self.PIN}})
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertTrue(code.last_push_error)

        code = self._update(code, gateway, {"lock_entity_ids": []})

        self.assertEqual(self._slots(code), {})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(code.last_push_error, "")
        self.assertEqual(code.push_attempt_count, 0)

    def test_dropping_every_lock_from_an_inactive_code_leaves_it_pushed(self):
        # Like a deactivate (#144), no lock holds anything for it, and the scheduler leaves it there.
        from locks.tasks import push_pending_door_codes

        code, gateway = self._pushed_code([self.BACK])
        code = self._update(code, gateway, {"is_active": False})
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.FAILED, last_push_error="old error")

        code = self._update(code, gateway, {"lock_entity_ids": []})

        self.assertEqual(self._slots(code), {})
        self.assertEqual((code.push_state, code.last_push_error), (DoorCode.PushState.PUSHED, ""))
        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_dropping_every_lock_keeps_the_code_pending_while_a_clear_is_still_outstanding(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        # BACK's push landed but was never confirmed, and its cleanup readback times out too.
        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        code, gateway = self._pushed_code([self.BACK], get_responses={12: [timeout] * 6})
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.FAILED, last_push_error="old error")

        code = self._update(code, gateway, {"lock_entity_ids": []})

        self.assertEqual(self._slots(code), {})
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        # Not reset like a code without locks. The state is the rollup now, so the
        # dropped lock's failure goes with it and the clear keeps it pending (issue #126).
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertNotIn("old error", code.last_push_error)
        self.assertTrue(code.last_push_error.startswith(f"Couldn't clear slot 1 on {self.BACK}"))

    def test_lock_lists_in_the_event_are_sorted(self):
        code, gateway = self._pushed_code([self.SIDE, self.FRONT])

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})
        self.assertEqual(self._updated_event(code).metadata["removed_lock_entity_ids"], [self.FRONT, self.SIDE])

        code = self._update(code, gateway, {"lock_entity_ids": [self.SIDE, self.FRONT, self.BACK]})
        self.assertEqual(self._updated_event(code).metadata["added_lock_entity_ids"], [self.FRONT, self.SIDE])


class ClearFailingGateway(FakeGateway):
    """A FakeGateway whose CC 99 ``clear`` times out on the nodes in ``clear_fails_on``."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.clear_fails_on: set[int] = set()

    def invoke_cc_api(self, *, node_id: int, command_class: int, method_name: str, args=None, timeout_seconds=10.0):
        if command_class == 99 and method_name == "clear" and node_id in self.clear_fails_on:
            from integrations_zwavejs.manager import ZwavejsCommandError

            self.invoke_calls.append(
                {"node_id": node_id, "command_class": command_class, "method_name": method_name, "args": list(args)}
            )
            raise ZwavejsCommandError("driver TimeoutError after 10.0s")
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class _TwoLockUpdateTestBase(EncryptionTestMixin, TestCase):
    BACK = "lock.back_door"  # node 12
    SIDE = "lock.side_door"  # node 13
    FRONT = "lock.front_door"  # node 14
    PIN = "4321"

    def setUp(self):
        self.user = User.objects.create_superuser(email="admin@example.com", password="pass")
        for entity_id, name, node_id in (
            (self.BACK, "Back Door", 12),
            (self.SIDE, "Side Door", 13),
            (self.FRONT, "Front Door", 14),
        ):
            Entity.objects.create(
                entity_id=entity_id,
                domain="lock",
                name=name,
                attributes={"zwavejs": {"node_id": node_id}},
                source="home_assistant",
            )
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _pushed_code(self, lock_entity_ids: list[str], **create_kwargs) -> tuple[DoorCode, ClearFailingGateway]:
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True)
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            lock_entity_ids=lock_entity_ids,
            actor_user=self.user,
            zwavejs=gateway,
            **create_kwargs,
        )
        gateway.invoke_calls.clear()
        return code, gateway

    def _update(self, code: DoorCode, gateway: FakeGateway, changes: dict) -> DoorCode:
        code = door_codes_uc.get_door_code_for_read(code_id=code.id)
        door_codes_uc.update_door_code(code=code, changes=changes, actor_user=self.user, zwavejs=gateway)
        return DoorCode.objects.get(id=code.id)

    def _deactivated_code(self, lock_entity_ids: list[str]) -> tuple[DoorCode, ClearFailingGateway]:
        code, gateway = self._pushed_code(lock_entity_ids)
        code = self._update(code, gateway, {"is_active": False})
        self.assertFalse(code.is_active)
        self.assertEqual(set(self._slots(code).values()), {None})
        gateway.invoke_calls.clear()
        return code, gateway

    _calls = staticmethod(LockListChangeTests._calls)
    _lock_codes = staticmethod(LockListChangeTests._lock_codes)

    def _slots(self, code: DoorCode) -> dict[str, int | None]:
        return dict(DoorCodeLockAssignment.objects.filter(door_code=code).values_list("lock_entity_id", "slot_index"))

    def _updated_event(self, code: DoorCode) -> DoorCodeEvent:
        return DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_UPDATED).latest(
            "id"
        )


class RequestPathClearTimeoutTests(_TwoLockUpdateTestBase):
    """Issue #124: the clears an update or delete runs in the request wait 5s, not the gateway's 10s."""

    def _clear_timeouts(self, gateway: FakeGateway) -> list[float]:
        return [timeout for method_name, timeout in gateway.invoke_timeouts if method_name == "clear"]

    def test_a_pin_change_clears_the_old_slot_with_a_5s_timeout(self):
        code, gateway = self._pushed_code([self.BACK])
        gateway.invoke_timeouts.clear()

        self._update(code, gateway, {"code": "5678"})

        self.assertEqual(self._clear_timeouts(gateway), [5.0])

    def test_dropping_a_lock_clears_its_slot_with_a_5s_timeout(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.invoke_timeouts.clear()

        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(self._clear_timeouts(gateway), [5.0])

    def test_a_delete_clears_its_slots_with_a_5s_timeout(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.invoke_timeouts.clear()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(self._clear_timeouts(gateway), [5.0, 5.0])


class InactiveCodeIsNeverPushedTests(_TwoLockUpdateTestBase):
    """Issue #138: nothing writes an inactive code's PIN to a lock."""

    def _assert_nothing_on_the_locks(self, gateway: FakeGateway) -> None:
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})

    def test_adding_a_lock_to_an_inactive_code_pushes_nothing(self):
        code, gateway = self._deactivated_code([self.BACK])

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK, self.SIDE]})

        self.assertEqual(gateway.invoke_calls, [])
        self._assert_nothing_on_the_locks(gateway)
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})
        self.assertFalse(code.is_active)

    def test_label_edit_on_an_inactive_code_pushes_nothing(self):
        code, gateway = self._deactivated_code([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"label": "Cleaner", "lock_entity_ids": [self.BACK, self.SIDE]})

        self.assertEqual(gateway.invoke_calls, [])
        self._assert_nothing_on_the_locks(gateway)
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_dropping_a_lock_from_an_inactive_code_pushes_nothing(self):
        code, gateway = self._deactivated_code([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self._assert_nothing_on_the_locks(gateway)
        self.assertEqual(self._slots(code), {self.BACK: None})

    def test_pin_change_on_an_inactive_code_pushes_nothing(self):
        code, gateway = self._deactivated_code([self.BACK])

        code = self._update(code, gateway, {"code": "5555"})

        self._assert_nothing_on_the_locks(gateway)
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_retry_on_an_inactive_code_is_refused_without_pushing(self):
        code, gateway = self._deactivated_code([self.BACK])
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.FAILED)

        with self.assertRaises(door_codes_uc.DoorCodeInactive):
            door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.FAILED)

    def test_push_skips_an_inactive_code(self):
        # create_door_code always makes active codes, so this guard is what keeps
        # any other caller (scheduler included) from pushing an inactive one.
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(self.PIN),
            pin_length=len(self.PIN),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=False,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.BACK)
        gateway = FakeGateway(usersNumber=5)

        result = push_door_code_to_assigned_locks(
            door_code=DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id), zwavejs=gateway
        )

        self.assertEqual(result, ([], []))
        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(DoorCode.objects.get(id=code.id).push_state, DoorCode.PushState.PENDING)

    def test_reactivating_pushes_again(self):
        code, gateway = self._deactivated_code([self.BACK])

        code = self._update(code, gateway, {"is_active": True})

        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN])])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)


class FailedSlotClearTests(_TwoLockUpdateTestBase):
    """Issue #139: a slot is only forgotten once its clear worked, and a failed clear stays visible and retried."""

    def _clear_events(self, code: DoorCode) -> list[dict]:
        return [
            {"lock": e.lock_entity_id, **e.metadata}
            for e in DoorCodeEvent.objects.filter(
                door_code=code, metadata__action__in=["clear_failed", "clear_resolved"]
            )
            .order_by("id")
            .only("lock_entity_id", "metadata")
        ]

    def _run_scheduler(self, gateway: FakeGateway) -> int:
        from locks.tasks import push_pending_door_codes

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            return push_pending_door_codes()

    def _pin_change_with_back_clear_failing(self, lock_entity_ids: list[str]) -> tuple[DoorCode, ClearFailingGateway]:
        code, gateway = self._pushed_code(lock_entity_ids)
        gateway.clear_fails_on = {12}
        code = self._update(code, gateway, {"code": "5555"})
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._slots(code)[self.BACK], 1)
        self.assertNotEqual(code.push_state, DoorCode.PushState.PUSHED)
        gateway.invoke_calls.clear()
        return code, gateway

    def _assert_not_pushed_while_back_holds_the_old_pin(self, code: DoorCode, gateway: FakeGateway) -> None:
        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._slots(code)[self.BACK], 1)
        self.assertNotEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)

    def test_dropped_lock_whose_clear_fails_keeps_its_slot_until_the_scheduler_clears_it(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.SIDE}", code.last_push_error)
        metadata = self._updated_event(code).metadata
        self.assertNotIn("removed_lock_entity_ids", metadata)
        self.assertEqual(
            [(f["lock_entity_id"], f["slot_index"]) for f in metadata["failed_slot_clears"]], [(self.SIDE, 1)]
        )
        self.assertIn("TimeoutError", metadata["failed_slot_clears"][0]["reason"])
        [event] = self._clear_events(code)
        self.assertEqual((event["lock"], event["action"], event["slot_index"]), (self.SIDE, "clear_failed", 1))
        self.assertTrue(event["removing"])

        # Still down: the scheduler tries again and the code stays pending.
        self.assertEqual(self._run_scheduler(gateway), 1)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})

        # Back up: the next tick clears the slot, finishes the removal and doesn't push there.
        gateway.clear_fails_on = set()
        gateway.invoke_calls.clear()
        self.assertEqual(self._run_scheduler(gateway), 1)

        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")
        self.assertEqual(self._clear_events(code)[-1]["action"], "clear_resolved")

    def test_dropping_a_lock_whose_entity_is_gone_still_drops_it(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        Entity.objects.filter(entity_id=self.SIDE).delete()

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(self._clear_events(code), [])
        metadata = self._updated_event(code).metadata
        self.assertEqual(metadata["removed_lock_entity_ids"], [self.SIDE])
        [failure] = metadata["failed_slot_clears"]
        self.assertEqual((failure["lock_entity_id"], failure["slot_index"], failure["permanent"]), (self.SIDE, 1, True))

    def test_pin_change_keeps_the_old_slot_when_its_clear_fails(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {12}

        code = self._update(code, gateway, {"code": "5555"})

        # Back still holds the old PIN in slot 1 and latchpoint still tracks it there,
        # instead of forgetting it and parking the new PIN in slot 2.
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._lock_codes(gateway, 13), {1: "5555"})
        self.assertEqual(self._calls(gateway, "set"), [(13, [1, 1, "5555"])])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        # Side's successful push doesn't hide Back's failed clear.
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)
        failed = self._updated_event(code).metadata["failed_slot_clears"]
        self.assertEqual([(f["lock_entity_id"], f["slot_index"]) for f in failed], [(self.BACK, 1)])

    def test_pin_change_while_dropping_a_lock_whose_clear_fails_tries_that_clear_once(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}

        code = self._update(code, gateway, {"code": "5555", "lock_entity_ids": [self.BACK]})

        self.assertEqual([c for c in self._calls(gateway, "clear") if c[0] == 13], [(13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, "5555"])])
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

    def test_adding_a_lock_after_a_failed_clear_does_not_mark_the_code_pushed(self):
        code, gateway = self._pin_change_with_back_clear_failing([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK, self.SIDE, self.FRONT]})

        self.assertEqual(self._calls(gateway, "set"), [(14, [1, 1, "5555"])])
        self._assert_not_pushed_while_back_holds_the_old_pin(code, gateway)

    def test_adding_a_lock_after_the_failure_is_past_event_retention_does_not_mark_the_code_pushed(self):
        from django.utils import timezone

        from alarm.models import SystemConfig
        from locks.tasks import cleanup_door_code_events

        code, gateway = self._pin_change_with_back_clear_failing([self.BACK, self.SIDE])
        SystemConfig.objects.create(
            key="door_code_events.retention_days",
            name="Door code event retention (days)",
            value_type="integer",
            value=90,
        )
        DoorCodeEvent.objects.filter(door_code=code).update(created_at=timezone.now() - timedelta(days=91))
        cleanup_door_code_events()

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK, self.SIDE, self.FRONT]})

        self._assert_not_pushed_while_back_holds_the_old_pin(code, gateway)

    def test_dropping_the_other_lock_after_a_failed_clear_does_not_mark_the_code_pushed(self):
        code, gateway = self._pin_change_with_back_clear_failing([self.BACK, self.SIDE])

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        self.assertEqual(self._slots(code), {self.BACK: 1})
        self._assert_not_pushed_while_back_holds_the_old_pin(code, gateway)

    def _pin_change_with_back_clear_failing_and_side_unconfirmed(self) -> tuple[DoorCode, ClearFailingGateway]:
        from integrations_zwavejs.manager import ZwavejsCommandError

        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {12}
        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway._get_scripts = {13: [timeout, timeout, timeout]}

        code = self._update(code, gateway, {"code": "5555"})

        # Side took the new PIN but its readback timed out, so it has no slot yet.
        self.assertEqual(self._lock_codes(gateway, 13), {1: "5555"})
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: None})
        self.assertNotEqual(code.push_state, DoorCode.PushState.PUSHED)
        gateway.invoke_calls.clear()
        return code, gateway

    def test_retry_with_the_clear_still_failing_does_not_mark_the_code_pushed(self):
        code, gateway = self._pin_change_with_back_clear_failing_and_side_unconfirmed()

        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self._assert_not_pushed_while_back_holds_the_old_pin(code, gateway)

    def test_retry_clears_the_stale_slot_first_then_pushes_the_new_pin(self):
        code, gateway = self._pin_change_with_back_clear_failing([self.BACK, self.SIDE])
        gateway.clear_fails_on = set()

        result = door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertEqual(self._lock_codes(gateway, 12), {1: "5555"})
        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self.assertEqual(self._calls(gateway, "set"), [(12, [1, 1, "5555"])])
        self.assertEqual(result.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(result.last_push_error, "")

    def test_scheduler_retries_a_failed_clear_alongside_a_transient_push_failure(self):
        code, gateway = self._pin_change_with_back_clear_failing_and_side_unconfirmed()

        # Back still down: Side gets confirmed, Back's clear is tried again.
        self.assertEqual(self._run_scheduler(gateway), 1)
        self.assertEqual(self._calls(gateway, "clear"), [(12, [1])])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self._assert_not_pushed_while_back_holds_the_old_pin(code, gateway)

        # Back up: cleared, then given the new PIN.
        gateway.clear_fails_on = set()
        self.assertEqual(self._run_scheduler(gateway), 1)

        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {1: "5555"})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")

    def test_failed_clear_that_keeps_failing_hits_the_attempt_cap(self):
        code, gateway = self._pin_change_with_back_clear_failing([self.BACK])

        with patch("locks.tasks._get_push_max_attempts", return_value=2):
            self._run_scheduler(gateway)
            self._run_scheduler(gateway)
            self.assertEqual(self._run_scheduler(gateway), 0)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertTrue(code.last_push_error.startswith(f"Couldn't clear slot 1 on {self.BACK}"))
        self.assertIn("Push gave up after 2 attempts", code.last_push_error)

    def test_deactivation_whose_clear_fails_is_retried_without_pushing(self):
        code, gateway = self._pushed_code([self.BACK])
        gateway.clear_fails_on = {12}

        code = self._update(code, gateway, {"is_active": False})

        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", code.last_push_error)

        # Retry is allowed on an inactive code while a clear is outstanding, but never pushes.
        door_codes_uc.retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

        gateway.clear_fails_on = set()
        gateway.invoke_calls.clear()
        self.assertEqual(self._run_scheduler(gateway), 1)

        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._slots(code), {self.BACK: None})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")

    def test_delete_refuses_when_a_clear_fails(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}

        with self.assertRaises(door_codes_uc.SlotClearFailed) as raised:
            door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertIn(f"Couldn't clear slot 1 on {self.SIDE}", str(raised.exception))
        code = DoorCode.objects.get(id=code.id)
        # Back was cleared so it's no longer tracked there; Side still is. The code
        # is turned off so the scheduler retries Side without pushing Back again.
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: 1})
        self.assertFalse(code.is_active)
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn(f"Couldn't clear slot 1 on {self.SIDE}", code.last_push_error)
        self.assertFalse(DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_DELETED).exists())

        # Once Side answers the delete goes through.
        gateway.clear_fails_on = set()
        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)
        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._lock_codes(gateway, 13), {})

    def test_refused_delete_never_pushes_onto_a_lock_an_earlier_clear_retry_freed(self):
        # Back's stale clear failed during a PIN change. At delete time Back answers
        # (the retry frees it) but Side doesn't, so the delete is refused.
        code, gateway = self._pin_change_with_back_clear_failing([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}

        with self.assertRaises(door_codes_uc.SlotClearFailed):
            door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        code.refresh_from_db()
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: 1})
        self.assertFalse(code.is_active)

        # The scheduler keeps retrying Side's clear and never puts 5555 back on Back.
        gateway.invoke_calls.clear()
        self.assertEqual(self._run_scheduler(gateway), 1)
        self.assertEqual(self._calls(gateway, "set"), [])
        gateway.clear_fails_on = set()
        self.assertEqual(self._run_scheduler(gateway), 1)

        code.refresh_from_db()
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_re_adding_a_lock_whose_drop_is_still_clearing_keeps_it(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}
        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})

        code = self._update(code, gateway, {"lock_entity_ids": [self.BACK, self.SIDE]})
        gateway.clear_fails_on = set()
        self._run_scheduler(gateway)

        code.refresh_from_db()
        # Side was cleared once it answered, but stays on the code and gets the PIN back.
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_a_failed_drop_of_a_lock_whose_entity_is_then_removed_is_settled_as_lock_missing(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}
        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})
        Entity.objects.filter(entity_id=self.SIDE).delete()
        gateway.invoke_calls.clear()

        self._run_scheduler(gateway)

        code.refresh_from_db()
        self.assertEqual([c for c in gateway.invoke_calls if c["node_id"] == 13], [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._clear_events(code)[-1]["outcome"], "lock_missing")
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def _record_failure(self, code: DoorCode, lock_entity_id: str, slot_index: int, **kwargs) -> None:
        from integrations_zwavejs.manager import ZwavejsCommandError

        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=lock_entity_id,
            slot_index=slot_index,
            exc=ZwavejsCommandError("driver TimeoutError after 10.0s"),
            **kwargs,
        )
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.PENDING)

    def test_a_failed_slot_no_longer_tracked_is_only_cleared_if_it_holds_the_expected_pin(self):
        code, gateway = self._pushed_code([self.BACK])
        gateway._lock_codes[(12, 3)] = "9999"  # someone else's code now
        gateway._lock_codes[(12, 4)] = self.PIN
        self._record_failure(code, self.BACK, 3, expected_pin=self.PIN)
        self._record_failure(code, self.BACK, 4, expected_pin=self.PIN)

        self._run_scheduler(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [(12, [4])])
        self.assertEqual(gateway._lock_codes[(12, 3)], "9999")
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN, 3: "9999"})
        outcomes = [e["outcome"] for e in self._clear_events(code) if e["action"] == "clear_resolved"]
        self.assertCountEqual(outcomes, ["not_holding_pin", "cleared"])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_an_unconfirmed_slot_holding_a_different_code_is_never_cleared(self):
        code, gateway = self._pushed_code([self.BACK])
        gateway._lock_codes[(12, 3)] = "9999"
        self._record_failure(code, self.BACK, 3, expected_pin=self.PIN, unconfirmed=True)

        self._run_scheduler(gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes[(12, 3)], "9999")
        self.assertEqual(self._clear_events(code)[-1]["outcome"], "not_holding_pin")

    def test_an_unconfirmed_slot_another_code_now_holds_is_left_alone(self):
        code, gateway = self._pushed_code([self.BACK])
        other = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("9999"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=other, lock_entity_id=self.BACK, slot_index=3)
        gateway._lock_codes[(12, 3)] = self.PIN  # even if it reads back like ours
        self._record_failure(code, self.BACK, 3, expected_pin=self.PIN, unconfirmed=True)
        gateway.invoke_calls.clear()

        self._run_scheduler(gateway)

        self.assertEqual([c for c in gateway.invoke_calls if c["args"] and c["args"][0] == 3], [])
        self.assertEqual(self._clear_events(code)[-1]["outcome"], "tracked")

    def test_delete_finishes_a_lock_drop_whose_clear_failed(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        gateway.clear_fails_on = {13}
        self._update(code, gateway, {"lock_entity_ids": [self.BACK]})
        gateway.clear_fails_on = set()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._lock_codes(gateway, 12), {})
        self.assertEqual(self._lock_codes(gateway, 13), {})

    def test_delete_skips_and_records_a_lock_whose_entity_is_gone(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])
        Entity.objects.filter(entity_id=self.SIDE).delete()

        door_codes_uc.delete_door_code(code=code, actor_user=self.user, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        metadata = DoorCodeEvent.objects.get(event_type=DoorCodeEvent.EventType.CODE_DELETED).metadata
        self.assertEqual(metadata["cleared_slots"], [{"lock_entity_id": self.BACK, "slot_index": 1}])
        [failure] = metadata["failed_slot_clears"]
        self.assertEqual((failure["lock_entity_id"], failure["slot_index"], failure["permanent"]), (self.SIDE, 1, True))


class FailedSlotClearDeleteApiTests(_TwoLockUpdateTestBase, APITestCase):
    def test_delete_with_an_unreachable_lock_returns_502_and_keeps_the_code(self):
        code, gateway = self._pushed_code([self.BACK])
        gateway.clear_fails_on = {12}
        self.client.force_authenticate(self.user)

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.delete(
                reverse("door-code-detail", args=[code.id]), {"reauth_password": "pass"}, format="json"
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn(f"Couldn't clear slot 1 on {self.BACK}", response.json()["error"]["message"])
        self.assertEqual(self._slots(DoorCode.objects.get(id=code.id)), {self.BACK: 1})


class EditFormSaveTests(_TwoLockUpdateTestBase, APITestCase):
    """Issue #139: the edit form sends every field, so only fields whose value changed trigger a re-push."""

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    def _form_save(self, door_code: DoorCode, gateway: FakeGateway, **overrides) -> DoorCode:
        # What DoorCodeEditContainer sends for a temporary code, values round-tripped from the API.
        url = reverse("door-code-detail", args=[door_code.id])
        current = self.client.get(url).json()["data"]
        body = {
            "label": current["label"],
            "is_active": current["is_active"],
            "max_uses": current["max_uses"],
            "lock_entity_ids": current["lock_entity_ids"],
            "start_at": current["start_at"],
            "end_at": current["end_at"],
            "days_of_week": current["days_of_week"],
            "window_start": current["window_start"],
            "window_end": current["window_end"],
            "reauth_password": "pass",
            **overrides,
        }
        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.patch(url, body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return DoorCode.objects.get(id=door_code.id)

    def _scheduled_code(self) -> tuple[DoorCode, ClearFailingGateway]:
        return self._pushed_code(
            [self.BACK, self.SIDE],
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b0011111,
            window_start=time(9, 0),
            window_end=time(17, 0),
        )

    def test_unchanged_save_makes_no_gateway_calls(self):
        code, gateway = self._scheduled_code()

        code = self._form_save(code, gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_unchanged_save_with_the_same_pin_and_short_times_makes_no_gateway_calls(self):
        # The time input gives "09:00" where the API returned "09:00:00", and the PIN
        # is stored encrypted, so neither can be compared as sent.
        code, gateway = self._scheduled_code()

        self._form_save(code, gateway, code=self.PIN, window_start="09:00", window_end="17:00")

        self.assertEqual(gateway.invoke_calls, [])

    def test_unchanged_save_with_a_failed_clear_on_a_lock_does_not_touch_it(self):
        code, gateway = self._scheduled_code()
        gateway.clear_fails_on = {12, 13}

        code = self._form_save(code, gateway, label="Cleaner")

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_changed_window_still_repushes_every_lock(self):
        code, gateway = self._scheduled_code()

        code = self._form_save(code, gateway, window_end="18:00")

        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertCountEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN]), (13, [1, 1, self.PIN])])
        self.assertEqual(code.window_end, time(18, 0))
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_changed_days_still_repushes(self):
        code, gateway = self._scheduled_code()

        self._form_save(code, gateway, days_of_week=0b1111111)

        self.assertCountEqual(self._calls(gateway, "set"), [(12, [1, 1, self.PIN]), (13, [1, 1, self.PIN])])

    def test_changed_pin_still_repushes(self):
        code, gateway = self._scheduled_code()

        self._form_save(code, gateway, code="5555")

        self.assertCountEqual(self._calls(gateway, "set"), [(12, [1, 1, "5555"]), (13, [1, 1, "5555"])])
        self.assertEqual(self._lock_codes(gateway, 12), {1: "5555"})

    def test_turning_the_code_off_from_the_form_clears_every_lock(self):
        code, gateway = self._scheduled_code()

        code = self._form_save(code, gateway, is_active=False)

        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._slots(code), {self.BACK: None, self.SIDE: None})


class LockListChangeApiTests(_TwoLockUpdateTestBase, APITestCase):
    """Issue #142: lock list changes through the PATCH view and serializer."""

    # Mon-Fri as set by _scheduled_code, as CC 78 slot ids (weekday bit + 1).
    WEEKDAY_SLOTS = [1, 2, 3, 4, 5]

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.user)

    _form_save = EditFormSaveTests._form_save
    _scheduled_code = EditFormSaveTests._scheduled_code

    @staticmethod
    def _schedule_calls(gateway: FakeGateway) -> list[tuple[int, int, int]]:
        return sorted(
            (c["node_id"], c["args"][0]["userId"], c["args"][0]["slotId"])
            for c in gateway.invoke_calls
            if c["command_class"] == 78 and c["method_name"] == "setDailyRepeatingSchedule"
        )

    def test_lock_change_through_the_api(self):
        code, gateway = self._pushed_code([self.BACK, self.SIDE])

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.patch(
                reverse("door-code-detail", args=[code.id]),
                {"lock_entity_ids": [self.FRONT, self.BACK], "reauth_password": "pass"},
                format="json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()["data"]
        self.assertEqual(data["lock_entity_ids"], [self.BACK, self.FRONT])
        fields = ("lock_entity_id", "slot_index", "pending_removal", "push_state", "schedule_pending")
        self.assertCountEqual(
            [{key: entry[key] for key in fields} for entry in data["lock_slot_assignments"]],
            [
                {
                    "lock_entity_id": self.BACK,
                    "slot_index": 1,
                    "pending_removal": False,
                    "push_state": DoorCode.PushState.PUSHED,
                    "schedule_pending": False,
                },
                {
                    "lock_entity_id": self.FRONT,
                    "slot_index": 1,
                    "pending_removal": False,
                    "push_state": DoorCode.PushState.PUSHED,
                    "schedule_pending": False,
                },
            ],
        )
        self.assertEqual(data["push_state"], DoorCode.PushState.PUSHED)
        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [(14, [1, 1, self.PIN])])
        metadata = self._updated_event(code).metadata
        self.assertEqual(metadata["added_lock_entity_ids"], [self.FRONT])
        self.assertEqual(metadata["removed_lock_entity_ids"], [self.SIDE])

    def test_saving_a_failed_code_with_no_locks_from_the_form_resets_it(self):
        code, gateway = self._scheduled_code()
        DoorCode.objects.filter(id=code.id).update(
            push_state=DoorCode.PushState.FAILED, last_push_error="Lock did not store the code"
        )

        code = self._form_save(code, gateway, lock_entity_ids=[])

        self.assertCountEqual(self._calls(gateway, "clear"), [(12, [1]), (13, [1])])
        self.assertEqual(self._slots(code), {})
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(code.last_push_error, "")

    def test_adding_a_lock_to_a_scheduled_code_pushes_the_pin_and_schedule_to_that_lock_only(self):
        code, gateway = self._scheduled_code()

        code = self._form_save(code, gateway, lock_entity_ids=[self.FRONT, self.BACK, self.SIDE])

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._calls(gateway, "set"), [(14, [1, 1, self.PIN])])
        self.assertEqual(self._schedule_calls(gateway), [(14, 1, slot) for slot in self.WEEKDAY_SLOTS])
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1, self.FRONT: 1})
        self.assertEqual((code.days_of_week, code.window_start, code.window_end), (0b0011111, time(9, 0), time(17, 0)))
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_dropping_a_lock_from_a_scheduled_code_only_clears_that_lock(self):
        code, gateway = self._scheduled_code()

        code = self._form_save(code, gateway, lock_entity_ids=[self.BACK])

        self.assertEqual(self._calls(gateway, "clear"), [(13, [1])])
        self.assertEqual(self._calls(gateway, "set"), [])
        self.assertEqual(self._schedule_calls(gateway), [])
        self.assertEqual(self._slots(code), {self.BACK: 1})
        self.assertEqual(self._lock_codes(gateway, 12), {1: self.PIN})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_a_kept_lock_still_pending_gets_pushed_by_a_lock_list_only_save(self):
        code, gateway = self._scheduled_code()
        # SIDE's push never got through: no slot, nothing on the lock.
        gateway._lock_codes.pop((13, 1))
        gateway._cache_codes.pop((13, 1))
        DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id=self.SIDE).update(slot_index=None)
        DoorCode.objects.filter(id=code.id).update(
            push_state=DoorCode.PushState.PENDING, last_push_error="Lock is not reachable right now; will retry."
        )

        code = self._form_save(code, gateway, lock_entity_ids=[self.BACK, self.SIDE, self.FRONT])

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertCountEqual(self._calls(gateway, "set"), [(13, [1, 1, self.PIN]), (14, [1, 1, self.PIN])])
        self.assertEqual(
            self._schedule_calls(gateway), [(node, 1, slot) for node in (13, 14) for slot in self.WEEKDAY_SLOTS]
        )
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1, self.FRONT: 1})
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
        self.assertEqual(code.last_push_error, "")

    def test_a_kept_lock_whose_push_went_unconfirmed_is_adopted_by_a_lock_list_only_save(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        # SIDE's set lands but every readback times out, so its slot is only on record.
        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = ClearFailingGateway(usersNumber=5, cache_updates_on_set=True, get_responses={13: [timeout] * 3})
        code = door_codes_uc.create_door_code(
            user=self.user,
            raw_code=self.PIN,
            lock_entity_ids=[self.BACK, self.SIDE],
            actor_user=self.user,
            zwavejs=gateway,
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b0011111,
            window_start=time(9, 0),
            window_end=time(17, 0),
        )
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: None})
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        gateway.invoke_calls.clear()

        code = self._form_save(code, gateway, lock_entity_ids=[self.BACK, self.SIDE, self.FRONT])

        # SIDE's slot is read back and kept instead of the PIN going into a second slot.
        self.assertEqual(self._calls(gateway, "set"), [(14, [1, 1, self.PIN])])
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(self._lock_codes(gateway, 13), {1: self.PIN})
        self.assertEqual(self._slots(code), {self.BACK: 1, self.SIDE: 1, self.FRONT: 1})
        adopted = DoorCodeEvent.objects.filter(
            door_code=code,
            lock_entity_id=self.SIDE,
            event_type=DoorCodeEvent.EventType.CODE_SYNCED,
            metadata__action="pushed",
        ).get()
        self.assertTrue(adopted.metadata["adopted_existing_slot"])
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)


class LockSlotAssignmentsSerializerTests(EncryptionTestMixin, TestCase):
    """ADR 0092: DoorCodeSerializer.get_lock_slot_assignments output + prefetch guard."""

    LOCK_ENTITY_ID = "lock.front_door"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )

    def test_returns_lock_entity_id_and_slot_index_when_prefetched(self):
        from locks.serializers import DoorCodeSerializer

        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("1234"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, slot_index=7)

        # Fetch through the queryset path the views use so lock_assignments is prefetched.
        fetched = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        data = DoorCodeSerializer(fetched).data

        self.assertEqual(
            data["lock_slot_assignments"],
            [
                {
                    "lock_entity_id": self.LOCK_ENTITY_ID,
                    "slot_index": 7,
                    "pending_removal": False,
                    "push_state": DoorCode.PushState.PENDING,
                    "last_push_error": "",
                    "last_push_attempt_at": None,
                    "push_attempt_count": 0,
                    "schedule_pending": False,
                    "push_requested_at": None,
                    "push_queued": False,
                }
            ],
        )

    def test_returns_null_slot_index_for_unpushed_assignment(self):
        from locks.serializers import DoorCodeSerializer

        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("1234"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, slot_index=None)

        fetched = DoorCode.objects.prefetch_related("lock_assignments").get(id=code.id)
        data = DoorCodeSerializer(fetched).data

        self.assertEqual(
            data["lock_slot_assignments"],
            [
                {
                    "lock_entity_id": self.LOCK_ENTITY_ID,
                    "slot_index": None,
                    "pending_removal": False,
                    "push_state": DoorCode.PushState.PENDING,
                    "last_push_error": "",
                    "last_push_attempt_at": None,
                    "push_attempt_count": 0,
                    "schedule_pending": False,
                    "push_requested_at": None,
                    "push_queued": False,
                }
            ],
        )

    def test_raises_runtime_error_when_lock_assignments_not_prefetched(self):
        from locks.serializers import DoorCodeSerializer

        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("1234"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)

        # Fetch WITHOUT prefetch_related — the guard must fire so a forgotten
        # prefetch becomes loud-test-failure instead of N+1 in prod.
        bare = DoorCode.objects.get(id=code.id)
        with self.assertRaises(RuntimeError):
            _ = DoorCodeSerializer(bare).data


class SanitizePushErrorForStorageTests(SimpleTestCase):
    """Defense-in-depth: digits that look PIN-shaped get masked before storage."""

    def test_masks_4_to_8_digit_runs(self):
        self.assertEqual(sanitize_push_error_for_storage("PIN was 1234"), "PIN was ****")
        self.assertEqual(sanitize_push_error_for_storage("rejected code 12345678"), "rejected code ****")

    def test_does_not_mask_short_digit_sequences(self):
        # slot index 5, node 109, HTTP 404 — all useful diagnostics that must survive.
        self.assertEqual(sanitize_push_error_for_storage("slot 5 node 109 status 404"), "slot 5 node 109 status 404")

    def test_does_not_mask_runs_longer_than_8(self):
        # ZJS home_ids are 10+ digits; not PIN-shaped.
        msg = "home_id 4170970308 unreachable"
        self.assertEqual(sanitize_push_error_for_storage(msg), msg)

    def test_does_not_mask_digits_inside_longer_numeric_runs(self):
        # "1234567890" is 10 digits — must not match because the lookarounds
        # require non-digit boundaries on both sides.
        msg = "request id 1234567890 timed out"
        self.assertEqual(sanitize_push_error_for_storage(msg), msg)

    def test_empty_and_none_inputs(self):
        self.assertEqual(sanitize_push_error_for_storage(""), "")
        self.assertEqual(sanitize_push_error_for_storage(None), "")

    def test_masks_pin_in_realistic_message(self):
        msg = 'ZwavejsCommandError: validator rejected userCode "13795"'
        sanitized = sanitize_push_error_for_storage(msg)
        self.assertNotIn("13795", sanitized)
        self.assertIn("****", sanitized)


class RetryPushDoorCodeUseCaseTests(EncryptionTestMixin, TestCase):
    """Direct unit tests for retry_push_door_code (the use case wrapped by the view)."""

    LOCK_ENTITY_ID = "lock.front_door"

    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )

    def _make_code(self, *, pin: str = "1234", push_state=DoorCode.PushState.PENDING, **kwargs) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=push_state,
            **kwargs,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        return code

    def test_retry_pushes_pending_code_and_flips_to_pushed(self):
        from locks.use_cases.door_codes import retry_push_door_code

        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234")

        result = retry_push_door_code(code=code, actor_user=self.admin, zwavejs=gateway)

        self.assertEqual(result.push_state, DoorCode.PushState.PUSHED)
        # CC 99 set was invoked with the 3-arg contract shape.
        set_calls = [c for c in gateway.invoke_calls if c["method_name"] == "set" and c["command_class"] == 99]
        self.assertEqual(len(set_calls), 1)
        self.assertEqual(set_calls[0]["args"][1], 1)  # userIdStatus = "Occupied"

    def test_retry_rearms_failed_codes_to_pending_and_zeros_attempt_count(self):
        from locks.use_cases.door_codes import retry_push_door_code

        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        # Start the code at FAILED with a non-zero counter — the operator is
        # saying "yes, try again."
        code = self._make_code(pin="2222", push_state=DoorCode.PushState.FAILED, push_attempt_count=24)

        result = retry_push_door_code(code=code, actor_user=self.admin, zwavejs=gateway)

        self.assertEqual(result.push_state, DoorCode.PushState.PUSHED)
        # Counter was zeroed before the push (and stayed zeroed on success).
        self.assertEqual(result.push_attempt_count, 0)

    def test_retry_requires_admin_actor(self):
        from locks.use_cases.door_codes import Forbidden, retry_push_door_code

        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="3333")

        with self.assertRaises(Forbidden):
            retry_push_door_code(code=code, actor_user=self.user, zwavejs=gateway)
        # Confirm we never reached the gateway with a non-admin actor.
        self.assertEqual(gateway.invoke_calls, [])


class DoorCodePushRetryViewTests(EncryptionTestMixin, APITestCase):
    """HTTP-level tests for POST /api/door-codes/<id>/push/ (ADR 0092)."""

    LOCK_ENTITY_ID = "lock.front_door"

    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )
        self.code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("4321"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=DoorCode.PushState.PENDING,
        )
        DoorCodeLockAssignment.objects.create(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID)

    def test_admin_retry_returns_200_and_omits_pin(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        self.client.force_authenticate(self.admin)
        url = reverse("door-code-push", args=[self.code.id])

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        # sa-1: plaintext PIN must NOT be returned by the retry endpoint.
        self.assertNotIn("pin", payload)
        # But the push-status fields the UI needs ARE present.
        self.assertEqual(payload["push_state"], DoorCode.PushState.PUSHED)
        self.assertIn("last_push_error", payload)
        self.assertIn("lock_slot_assignments", payload)

    def test_retry_on_an_inactive_code_returns_409_without_pushing(self):
        DoorCode.objects.filter(id=self.code.id).update(is_active=False)
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        self.client.force_authenticate(self.admin)
        url = reverse("door-code-push", args=[self.code.id])

        with patch("locks.views.door_codes.default_zwavejs_gateway", gateway):
            response = self.client.post(url)

        self.assertEqual(response.status_code, 409)
        self.assertIn("inactive", response.json()["error"]["message"])
        self.assertEqual(gateway.invoke_calls, [])

    def test_non_admin_user_gets_403(self):
        self.client.force_authenticate(self.user)
        url = reverse("door-code-push", args=[self.code.id])

        response = self.client.post(url)

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_gets_401_or_403(self):
        url = reverse("door-code-push", args=[self.code.id])

        response = self.client.post(url)

        self.assertIn(response.status_code, (401, 403))

    def test_unknown_code_id_returns_404(self):
        self.client.force_authenticate(self.admin)
        url = reverse("door-code-push", args=[999_999])

        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)


class AdminCodeHintVisibilityTests(EncryptionTestMixin, APITestCase):
    """PR #198 review: only admins see that a PIN may match the lock's admin code (issue #125)."""

    LOCK_ENTITY_ID = "lock.front_door"

    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("4321"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID)
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321")
        with self.assertRaises(LockRejectedCode):
            push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.code.refresh_from_db()
        # Stored with the hint, on the code and on the lock.
        self.assertIn(lock_push_uc._ADMIN_CODE_HINT, self.code.last_push_error)
        self.assertIn(
            lock_push_uc._ADMIN_CODE_HINT, DoorCodeLockAssignment.objects.get(door_code=self.code).last_push_error
        )

    def _errors(self, payload: dict) -> list[str]:
        return [payload["last_push_error"], *(lock["last_push_error"] for lock in payload["lock_slot_assignments"])]

    def test_the_owner_doesnt_see_the_hint(self):
        self.client.force_authenticate(self.user)

        detail = self.client.get(reverse("door-code-detail", args=[self.code.id])).json()["data"]
        [listed] = self.client.get(reverse("door-codes")).json()["data"]

        for payload in (detail, listed):
            for error in self._errors(payload):
                self.assertIn("reads back empty", error)
                self.assertNotIn("admin code", error)

    def test_an_admin_sees_the_hint(self):
        self.client.force_authenticate(self.admin)

        detail = self.client.get(reverse("door-code-detail", args=[self.code.id])).json()["data"]
        [listed] = self.client.get(reverse("door-codes"), {"user_id": str(self.user.id)}).json()["data"]

        for payload in (detail, listed):
            for error in self._errors(payload):
                self.assertIn(lock_push_uc._ADMIN_CODE_HINT, error)

    def test_without_a_request_the_hint_is_left_out(self):
        from locks.serializers import DoorCodeSerializer

        code = DoorCode.objects.prefetch_related("lock_assignments").get(id=self.code.id)

        for error in self._errors(DoorCodeSerializer(code).data):
            self.assertNotIn("admin code", error)

    def test_a_hint_cut_short_at_the_end_of_a_full_length_error_is_stripped(self):
        hint = lock_push_uc._ADMIN_CODE_HINT
        full = f"{'x' * (500 - len(hint) + 9)} {hint}"[:500]
        self.assertEqual(len(full), 500)
        self.assertNotIn(hint, full)

        self.assertEqual(lock_push_uc.strip_admin_code_hint(full), "x" * (500 - len(hint) + 9))
        self.assertEqual(
            lock_push_uc.strip_admin_code_hint(f"lock.a: Lock did not store the code. {hint}; lock.b: timeout"),
            "lock.a: Lock did not store the code.; lock.b: timeout",
        )

    def test_a_full_length_error_ending_in_the_hints_first_words_only_loses_a_real_cut_hint(self):
        # PR #198 review: " This" or " This PIN" at the end of any 500 character error isn't the hint.
        for ending in (" T", " This", " This PIN", " This PIN m"):
            message = f"{'x' * (500 - len(ending))}{ending}"
            self.assertEqual(lock_push_uc.strip_admin_code_hint(message), message)
        for ending in (" This PIN may", " This PIN may match the lock's adm"):
            message = f"{'x' * (500 - len(ending))}{ending}"
            self.assertEqual(lock_push_uc.strip_admin_code_hint(message), "x" * (500 - len(ending)))
        # Under 500 characters nothing was cut, so only the whole hint goes. Pinned at the boundary.
        self.assertEqual(lock_push_uc.strip_admin_code_hint("x This PIN may"), "x This PIN may")
        ending = " This PIN may match"
        at_499 = f"{'x' * (499 - len(ending))}{ending}"
        self.assertEqual(len(at_499), 499)
        self.assertEqual(lock_push_uc.strip_admin_code_hint(at_499), at_499)
        at_500 = f"x{at_499}"
        self.assertEqual(lock_push_uc.strip_admin_code_hint(at_500), "x" * (500 - len(ending)))

    # PR #198 review: the create, PATCH and Retry responses keep the hint for an admin,
    # which needs the request in the serializer context.

    def _admin_errors_from(self, method: str, url: str, data: dict, use_case: str) -> list[str]:
        code = DoorCode.objects.select_related("user").prefetch_related("lock_assignments").get(id=self.code.id)
        self.client.force_authenticate(self.admin)
        with patch.object(door_codes_uc, use_case, return_value=code):
            response = getattr(self.client, method)(url, data, format="json")
        self.assertLess(response.status_code, 300, response.content)
        return self._errors(response.json()["data"])

    def test_the_create_response_keeps_the_hint_for_an_admin(self):
        errors = self._admin_errors_from(
            "post",
            reverse("door-codes"),
            {
                "user_id": str(self.user.id),
                "code": "4321",
                "code_type": DoorCode.CodeType.PERMANENT,
                "lock_entity_ids": [self.LOCK_ENTITY_ID],
                "reauth_password": "pass",
            },
            "create_door_code",
        )

        for error in errors:
            self.assertIn(lock_push_uc._ADMIN_CODE_HINT, error)

    def test_the_patch_response_keeps_the_hint_for_an_admin(self):
        errors = self._admin_errors_from(
            "patch",
            reverse("door-code-detail", args=[self.code.id]),
            {"label": "Cleaner", "reauth_password": "pass"},
            "update_door_code",
        )

        for error in errors:
            self.assertIn(lock_push_uc._ADMIN_CODE_HINT, error)

    def test_the_retry_response_keeps_the_hint_for_an_admin(self):
        errors = self._admin_errors_from(
            "post", reverse("door-code-push", args=[self.code.id]), {}, "retry_push_door_code"
        )

        for error in errors:
            self.assertIn(lock_push_uc._ADMIN_CODE_HINT, error)


class PushSlotClaimRaceTests(EncryptionTestMixin, TestCase):
    """Issue #106: back-to-back pushes must not land in the same slot.

    ``FakeGateway``'s value cache doesn't see a ``set`` unless
    ``deliver_late_reports()`` runs, which is the stale Z-Wave JS value cache the
    bug depends on.
    """

    LOCK_ENTITY_ID = "lock.front_door"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )

    def _make_code(self, *, pin: str, slot_index: int | None = None, **kwargs) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=kwargs.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=True,
            **kwargs,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, slot_index=slot_index)
        return code

    def _slot_of(self, code: DoorCode) -> int | None:
        return DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID).slot_index

    def _set_slots(self, gateway: FakeGateway) -> list[int]:
        return [c["args"][0] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "set"]

    def test_back_to_back_pushes_pick_different_slots_while_cache_is_stale(self):
        gateway = FakeGateway(usersNumber=5, slot_status=dict.fromkeys(range(1, 6), 0))
        codes = [self._make_code(pin=pin) for pin in ("1111", "2222", "3333")]

        for code in codes:
            successes, failures = push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway)
            self.assertEqual(failures, [])
            self.assertEqual(len(successes), 1)

        self.assertEqual(self._set_slots(gateway), [1, 2, 3])
        self.assertEqual([self._slot_of(code) for code in codes], [1, 2, 3])

    def test_skips_slot_already_assigned_in_db(self):
        # The cache says slot 1 is Available but another code owns it in the DB.
        self._make_code(pin="9999", slot_index=1)
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234")

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 2)
        self.assertEqual(self._set_slots(gateway), [2])

    def test_slots_full_when_every_free_cache_slot_is_claimed_in_db(self):
        self._make_code(pin="9999", slot_index=1)
        self._make_code(pin="8888", slot_index=2)
        gateway = FakeGateway(usersNumber=2, slot_status={1: 0, 2: 0})
        code = self._make_code(pin="1234")

        with self.assertRaises(LockSlotsFull):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(self._set_slots(gateway), [])

    def test_push_interrupted_mid_set_leaves_slot_unassigned_for_retry(self):
        # A process killed mid-push (redeploy, OOM, Ctrl-C) must not leave a slot
        # recorded, or the scheduler's slot_index IS NULL filter never retries it.
        class InterruptingGateway(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                if command_class == 99 and method_name == "set":
                    raise KeyboardInterrupt
                return super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )

        gateway = InterruptingGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234")

        with self.assertRaises(KeyboardInterrupt):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertIsNone(self._slot_of(code))
        self.assertTrue(
            DoorCodeLockAssignment.objects.filter(
                door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, slot_index__isnull=True
            ).exists()
        )

    def test_slot_recorded_for_another_code_during_push_fails_terminally(self):
        # Another writer records the same slot while our CC 99 set is in flight.
        # The success-path write must not double-book it or blow up unhandled.
        lock_entity_id = self.LOCK_ENTITY_ID
        other = self._make_code(pin="9999")

        class ConcurrentWriterGateway(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                if command_class == 99 and method_name == "set":
                    DoorCodeLockAssignment.objects.filter(door_code=other, lock_entity_id=lock_entity_id).update(
                        slot_index=args[0]
                    )
                return super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )

        gateway = ConcurrentWriterGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234")

        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertIsNone(self._slot_of(code))
        self.assertEqual(self._slot_of(other), 1)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertIn("recorded for another door code", code.last_push_error)

    def _push_while_other_records_slot(self, *, other: DoorCode, pin: str = "1234") -> tuple[DoorCode, FakeGateway]:
        """Push a new code while ``other`` gets the same slot recorded mid-push (issue #129)."""
        lock_entity_id = self.LOCK_ENTITY_ID

        class ConcurrentWriterGateway(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                if command_class == 99 and method_name == "set":
                    DoorCodeLockAssignment.objects.filter(door_code=other, lock_entity_id=lock_entity_id).update(
                        slot_index=args[0]
                    )
                return super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )

        gateway = ConcurrentWriterGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin=pin)
        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        return code, gateway

    def test_slot_recorded_for_another_code_names_that_code_and_asks_for_a_lock_sync(self):
        other = self._make_code(pin="9999", label="Dog walker")

        code, _gateway = self._push_while_other_records_slot(other=other)

        code.refresh_from_db()
        self.assertIn(f'another door code (id {other.id}, "Dog walker") during the push', code.last_push_error)
        self.assertIn("may now hold this PIN in slot 1 in place of that code's", code.last_push_error)
        self.assertIn(f"Run a lock sync on {self.LOCK_ENTITY_ID}", code.last_push_error)
        event = DoorCodeEvent.objects.get(door_code=code, metadata__action="push")
        self.assertEqual(event.lock_entity_id, self.LOCK_ENTITY_ID)
        self.assertEqual(event.metadata["conflicting_door_code_id"], other.id)
        self.assertEqual(event.metadata["conflicting_door_code_label"], "Dog walker")
        self.assertEqual(event.metadata["conflicting_door_code_source"], DoorCode.Source.MANUAL)
        self.assertEqual(event.metadata["slot_index"], 1)
        self.assertTrue(event.metadata["lock_sync_needed"])
        self.assertEqual(
            event.metadata["next_step"],
            f"Run a lock sync on {self.LOCK_ENTITY_ID} to check what the slot holds before retrying.",
        )
        self.assertIn("in place of that code's", event.metadata["reason"])

    def test_owner_without_a_label_is_named_by_id_only(self):
        other = self._make_code(pin="9999", label="")

        code, _gateway = self._push_while_other_records_slot(other=other)

        code.refresh_from_db()
        self.assertIn(f"another door code (id {other.id}) during the push", code.last_push_error)
        self.assertNotIn('"', code.last_push_error)

    def test_synced_owner_says_the_lock_sync_takes_this_pin_and_to_drop_the_lock(self):
        other = self._make_code(pin="9999", label="Slot 1", source=DoorCode.Source.SYNCED)

        code, _gateway = self._push_while_other_records_slot(other=other)

        code.refresh_from_db()
        self.assertIn("imported by a lock sync", code.last_push_error)
        self.assertIn(f"remove {self.LOCK_ENTITY_ID} from this code instead of retrying", code.last_push_error)
        event = DoorCodeEvent.objects.get(door_code=code, metadata__action="push")
        self.assertEqual(event.metadata["conflicting_door_code_source"], DoorCode.Source.SYNCED)
        self.assertIn("instead of retrying", event.metadata["next_step"])

    def test_owner_gone_by_the_lookup_still_explains_the_slot(self):
        from django.db import IntegrityError
        from django.db.models.query import QuerySet

        real_update = QuerySet.update

        def update(queryset, **kwargs):
            if queryset.model is DoorCodeLockAssignment and kwargs.get("slot_index") is not None:
                raise IntegrityError("door_code_lock_assignments_unique_lock_slot")
            return real_update(queryset, **kwargs)

        gateway = FakeGateway(usersNumber=3)
        code = self._make_code(pin="1234")

        with patch.object(QuerySet, "update", update), self.assertRaises(LockPushFailed):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertIn("recorded for another door code during the push", code.last_push_error)
        self.assertIn("in place of the code recorded there", code.last_push_error)
        event = DoorCodeEvent.objects.get(door_code=code, metadata__action="push")
        self.assertIsNone(event.metadata["conflicting_door_code_id"])
        self.assertIsNone(event.metadata["conflicting_door_code_label"])
        self.assertTrue(DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed").exists())

    def test_slot_recorded_for_another_code_is_kept_as_an_unconfirmed_slot(self):
        other = self._make_code(pin="9999")

        code, _gateway = self._push_while_other_records_slot(other=other)

        marker = DoorCodeEvent.objects.get(door_code=code, metadata__action="push_unconfirmed")
        self.assertEqual(marker.lock_entity_id, self.LOCK_ENTITY_ID)
        self.assertEqual(marker.metadata["slot_index"], 1)
        self.assertEqual(lock_push_uc._decrypt_expected_pin(marker.metadata), "1234")

    def test_delete_leaves_the_slot_alone_while_the_other_code_holds_it(self):
        other = self._make_code(pin="9999")
        code, gateway = self._push_while_other_records_slot(other=other)
        calls_before = len(gateway.invoke_calls)

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(gateway.invoke_calls[calls_before:], [])
        self.assertEqual(self._slot_of(other), 1)

    def test_retry_adopts_the_slot_once_the_other_code_lets_go_of_it(self):
        other = self._make_code(pin="9999")
        code, gateway = self._push_while_other_records_slot(other=other)
        # The other code forgets slot 1 without clearing it, ie its readback found this PIN there.
        DoorCodeLockAssignment.objects.filter(door_code=other).update(slot_index=None)

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 1)
        self.assertEqual(self._set_slots(gateway), [1])
        self.assertEqual(self._slot_of(code), 1)

    def test_delete_clears_the_slot_once_the_other_code_lets_go_of_it(self):
        other = self._make_code(pin="9999")
        code, gateway = self._push_while_other_records_slot(other=other)
        DoorCodeLockAssignment.objects.filter(door_code=other).update(slot_index=None)

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        clears = [c["args"] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "clear"]
        self.assertEqual(clears, [[1]])
        self.assertNotIn((7, 1), gateway._lock_codes)

    MASKED = {"userIdStatus": 1, "userCode": "****"}

    def _die_at_the_slot_commit(self, *, drops_duplicates: bool, masked: bool = False) -> tuple[DoorCode, FakeGateway]:
        """Push with the process dying in the transaction that records slot 1, after the PIN landed there (issue #130).

        ``masked`` makes every CC 99 ``get`` answer occupied with a masked code, like a lock that hides PINs.
        """
        gateway = FakeGateway(
            usersNumber=3,
            slot_status={1: 0, 2: 0, 3: 0},
            cache_updates_on_set=True,
            drops_duplicates=drops_duplicates,
            get_responses=[self.MASKED] * 20 if masked else None,
        )
        code = self._make_code(pin="1234")

        # The code's rollup is the last write of the slot's transaction (issue #126).
        with (
            patch.object(lock_push_uc, "refresh_push_state", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
        return code, gateway

    def test_process_dying_in_the_slot_commit_records_no_slot(self):
        # The slot, the lock's state and the code's rollup commit together, so the
        # code isn't left pending with a slot nothing retries.
        code, _gateway = self._die_at_the_slot_commit(drops_duplicates=True)

        self.assertIsNone(self._slot_of(code))
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertFalse(DoorCodeEvent.objects.filter(door_code=code, metadata__action="pushed").exists())

    def test_retry_after_dying_at_the_slot_commit_adopts_the_slot_and_delete_clears_it(self):
        # PR #190 review: the rollback must not lose the slot the PIN already landed in.
        for drops_duplicates in (False, True):
            with self.subTest(drops_duplicates=drops_duplicates):
                code, gateway = self._die_at_the_slot_commit(drops_duplicates=drops_duplicates)

                result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

                self.assertEqual(result.slot_index, 1)
                self.assertEqual(self._set_slots(gateway), [1])
                self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
                code.refresh_from_db()
                self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

                door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

                self.assertEqual(gateway._lock_codes, {})

    def test_delete_after_dying_at_the_slot_commit_clears_the_slot(self):
        for drops_duplicates in (False, True):
            with self.subTest(drops_duplicates=drops_duplicates):
                code, gateway = self._die_at_the_slot_commit(drops_duplicates=drops_duplicates)

                door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

                self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
                self.assertEqual(gateway._lock_codes, {})

    def test_masked_lock_retry_after_dying_at_the_slot_commit_adopts_the_slot_and_delete_clears_it(self):
        # PR #190 review: a lock that masks PINs can't show the PIN on the retry's
        # readback, so the push's own earlier readback has to count.
        for drops_duplicates in (False, True):
            with self.subTest(drops_duplicates=drops_duplicates):
                code, gateway = self._die_at_the_slot_commit(drops_duplicates=drops_duplicates, masked=True)

                result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

                self.assertEqual(result.slot_index, 1)
                self.assertEqual(self._set_slots(gateway), [1])
                door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

                self.assertEqual(gateway._lock_codes, {})

    def test_masked_lock_delete_after_dying_at_the_slot_commit_clears_the_slot(self):
        for drops_duplicates in (False, True):
            with self.subTest(drops_duplicates=drops_duplicates):
                code, gateway = self._die_at_the_slot_commit(drops_duplicates=drops_duplicates, masked=True)

                door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

                self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
                self.assertEqual(gateway._lock_codes, {})

    def test_masked_lock_failed_clear_of_a_rolled_back_slot_is_retried_after_a_pin_change_lands(self):
        # PR #190 review: the slot_verified tag has to survive on the clear failure,
        # since the new PIN's push closes the attempt's window on that lock.
        from integrations_zwavejs.manager import ZwavejsCommandError

        code, gateway = self._die_at_the_slot_commit(drops_duplicates=False, masked=True)
        real_invoke = gateway.invoke_cc_api

        def clear_fails(**kwargs):
            if kwargs.get("command_class") == 99 and kwargs.get("method_name") == "clear":
                raise ZwavejsCommandError("driver TimeoutError after 5.0s")
            return real_invoke(**kwargs)

        with patch.object(gateway, "invoke_cc_api", clear_fails):
            door_codes_uc.update_door_code(code=code, changes={"code": "5678"}, zwavejs=gateway)

        self.assertEqual(self._slot_of(code), 2)
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234", (7, 2): "5678"})
        failures = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertEqual([(f.slot_index, f.unconfirmed, f.slot_verified) for f in failures], [(1, True, True)])

        still_failing = lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)

        self.assertEqual(still_failing, [])
        self.assertEqual(gateway._lock_codes, {(7, 2): "5678"})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])

    def test_masked_slot_of_a_tagged_attempt_with_an_older_pin_is_not_adopted(self):
        # A tagged attempt only vouches for the PIN it sent: after a PIN change the
        # masked slot may still hold the old PIN, so the new one goes in a new slot.
        code = self._make_code(pin="1234")
        self._attempt_on_slot_1(code=code, slot_verified=True)
        DoorCode.objects.filter(id=code.id).update(encrypted_pin=SettingsEncryption.get().encrypt("5678"))
        gateway = FakeGateway(
            usersNumber=3, slot_status={1: 1, 2: 0, 3: 0}, get_responses=[self.MASKED] * 20, cache_updates_on_set=True
        )
        gateway._lock_codes[(7, 1)] = "1234"

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 2)
        self.assertEqual(self._set_slots(gateway), [2])
        self.assertEqual(gateway._lock_codes[(7, 2)], "5678")

    def test_masked_slot_of_a_tagged_attempt_with_the_same_pin_is_adopted(self):
        code = self._make_code(pin="1234")
        self._attempt_on_slot_1(code=code, slot_verified=True)
        gateway = FakeGateway(usersNumber=3, slot_status={1: 1, 2: 0, 3: 0}, get_responses=[self.MASKED] * 20)
        gateway._lock_codes[(7, 1)] = "1234"

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 1)
        self.assertEqual(self._set_slots(gateway), [])

    def _attempt_on_slot_1(self, *, code: DoorCode, slot_verified: bool) -> None:
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            slot_index=1,
            reason="timeout",
            pin="1234",
            slot_verified=slot_verified,
        )

    def test_masked_slot_of_an_untagged_attempt_is_left_alone(self):
        # Only the attempt the push recorded after its own readback counts a masked slot as its own.
        code = self._make_code(pin="1234")
        self._attempt_on_slot_1(code=code, slot_verified=False)
        gateway = FakeGateway(usersNumber=3, get_responses=[self.MASKED] * 20)
        gateway._lock_codes[(7, 1)] = "1234"

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(any(c["method_name"] == "clear" for c in gateway.invoke_calls))
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})

    def test_tagged_attempt_never_clears_a_readable_different_code_or_a_config_slot(self):
        for response in (
            {"userIdStatus": 1, "userCode": "5555"},
            {"userIdStatus": 3},
            {"userIdStatus": 4},
            {"userIdStatus": 0, "userCode": ""},
        ):
            with self.subTest(response=response):
                code = self._make_code(pin="1234")
                self._attempt_on_slot_1(code=code, slot_verified=True)
                gateway = FakeGateway(usersNumber=3, get_responses=[response] * 20)

                with patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)):
                    door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

                self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
                self.assertFalse(any(c["method_name"] == "clear" for c in gateway.invoke_calls))

    def test_tagged_masked_slot_another_code_holds_is_left_alone(self):
        other = self._make_code(pin="9999", slot_index=1)
        code = self._make_code(pin="1234")
        self._attempt_on_slot_1(code=code, slot_verified=True)
        gateway = FakeGateway(usersNumber=3, get_responses=[self.MASKED] * 20)

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(self._slot_of(other), 1)

    def test_successful_push_leaves_no_unconfirmed_marker(self):
        gateway = FakeGateway(usersNumber=3)
        code = self._make_code(pin="1234")

        push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertFalse(DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed").exists())
        self.assertEqual(
            list(DoorCodeEvent.objects.filter(door_code=code).values_list("event_type", flat=True)),
            [DoorCodeEvent.EventType.CODE_SYNCED],
        )

    def test_single_cc_99_get_after_set_is_the_readback(self):
        # The #107 readback is also the cache refresh #106 added: one get per push,
        # never a second one after the success stamp (battery locks).
        gateway = FakeGateway(usersNumber=3, slot_status={1: 1, 2: 0, 3: 0})
        code = self._make_code(pin="1234")

        push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        cc99 = [(c["method_name"], c["args"]) for c in gateway.invoke_calls if c["command_class"] == 99]
        self.assertEqual(cc99, [("set", [2, 1, "1234"]), ("get", [2])])

    def test_failed_readback_get_leaves_push_pending_without_slot(self):
        # Before #107 the get was a best-effort refresh after the success stamp, so
        # a failed get still meant pushed. It's now the readback that decides
        # success: every attempt failing leaves the row pending with no slot.
        from integrations_zwavejs.manager import ZwavejsCommandError

        class GetFailsGateway(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                result = super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )
                if command_class == 99 and method_name == "get":
                    raise ZwavejsCommandError("driver TimeoutError after 5.0s")
                return result

        gateway = GetFailsGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0})
        code = self._make_code(pin="1234")

        with (
            patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)),
            self.assertRaises(LockUnreachable),
        ):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        gets = [c for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "get"]
        self.assertEqual(len(gets), 1 + len(lock_push_uc._READBACK_RETRY_DELAYS_SECONDS))
        self.assertIsNone(self._slot_of(code))
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)
        self.assertIn("LockCodeUnverified", code.last_push_error)


class SlotStatusFreeTests(EncryptionTestMixin, TestCase):
    """Issue #168: only a userIdStatus of Available (0) makes a slot free."""

    LOCK_ENTITY_ID = "lock.front_door"
    MESSAGING = 3
    PASSAGE_MODE = 4
    STATUS_NOT_AVAILABLE = 0xFE

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )
        self.code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("1234"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID)

    @staticmethod
    def _set_slots(gateway: FakeGateway) -> list[int]:
        return [c["args"][0] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "set"]

    def test_messaging_and_passage_mode_slots_are_skipped(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: self.MESSAGING, 2: self.PASSAGE_MODE, 3: 0})

        result = push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 3)
        self.assertEqual(self._set_slots(gateway), [3])

    def test_lock_with_only_messaging_and_passage_mode_slots_is_full(self):
        gateway = FakeGateway(usersNumber=2, slot_status={1: self.MESSAGING, 2: self.PASSAGE_MODE})

        with self.assertRaises(LockSlotsFull):
            push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=self.code).slot_index)

    def test_status_not_available_or_missing_is_not_free(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: self.STATUS_NOT_AVAILABLE, 2: None, 3: 0})

        result = push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 3)
        self.assertEqual(self._set_slots(gateway), [3])

    def test_reads_the_status_on_the_locks_own_cc_99_endpoint(self):
        class EndpointGateway(FakeGateway):
            def node_get_defined_value_ids(self, *, node_id, timeout_seconds=5.0):
                return [
                    {**vid, "endpoint": 1}
                    for vid in super().node_get_defined_value_ids(node_id=node_id, timeout_seconds=timeout_seconds)
                ]

            def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
                if value_id.get("property") == "userIdStatus" and value_id.get("endpoint") != 1:
                    return None  # nothing cached under a value id without the endpoint
                return super().node_get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)

        gateway = EndpointGateway(usersNumber=3, slot_status={1: 1, 2: 0, 3: 0})

        result = push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 2)

    def test_slots_full_counts_toward_the_attempt_cap(self):
        gateway = FakeGateway(usersNumber=2, slot_status={1: self.MESSAGING, 2: 1})

        for attempt in (1, 2):
            with self.assertRaises(LockSlotsFull):
                push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
            self.code.refresh_from_db()
            # Counted on the lock, which the cap is on now (issue #126).
            assignment = DoorCodeLockAssignment.objects.get(door_code=self.code)
            self.assertEqual(assignment.push_attempt_count, attempt)
            self.assertEqual(self.code.push_state, DoorCode.PushState.PENDING)
            self.assertIn("No user-code slot on this lock is Available", self.code.last_push_error)

    def test_scheduler_gives_up_on_a_lock_with_nothing_available(self):
        from locks.tasks import _get_push_max_attempts, push_pending_door_codes

        gateway = FakeGateway(usersNumber=2, slot_status={1: self.MESSAGING, 2: self.PASSAGE_MODE})
        # The cap is on the lock's own count now (issue #126).
        DoorCodeLockAssignment.objects.filter(door_code=self.code).update(
            push_attempt_count=_get_push_max_attempts() - 1
        )

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        self.code.refresh_from_db()
        self.assertEqual(self.code.push_state, DoorCode.PushState.FAILED)
        self.assertEqual(self._set_slots(gateway), [])

    def _record_attempt(self, slot_index: int) -> None:
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, slot_index=slot_index, reason="timeout", pin="1234"
        )

    def test_attempt_slot_reading_messaging_or_passage_mode_is_skipped_by_adoption(self):
        class ConfigSlotGateway(FakeGateway):
            """Slot 1 answers every CC 99 ``get`` with ``config_status``."""

            config_status = 0

            def _handle_user_code_call(self, *, node_id, method_name, args):
                if method_name == "get" and int(args[0]) == 1:
                    return {"userIdStatus": self.config_status}
                return super()._handle_user_code_call(node_id=node_id, method_name=method_name, args=args)

        for status in (self.MESSAGING, self.PASSAGE_MODE):
            with self.subTest(status=status):
                DoorCodeLockAssignment.objects.filter(door_code=self.code).update(slot_index=None)
                self._record_attempt(1)
                gateway = ConfigSlotGateway(usersNumber=3, slot_status={1: status, 2: 0, 3: 0})
                gateway.config_status = status

                with patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)):
                    result = push_door_code_to_lock(
                        door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway
                    )

                self.assertEqual(result.slot_index, 2)
                self.assertEqual(self._set_slots(gateway), [2])

    def test_unconfirmed_cleanup_settles_a_messaging_or_passage_mode_slot_without_clearing_it(self):
        for status in (self.MESSAGING, self.PASSAGE_MODE):
            with self.subTest(status=status):
                self._record_attempt(1)
                gateway = FakeGateway(usersNumber=3, get_responses=[{"userIdStatus": status}] * 3)

                with patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)):
                    cleared, failed = lock_push_uc.clear_unconfirmed_slots_holding_pin(
                        door_code=self.code, pin="1234", lock_entity_ids=[self.LOCK_ENTITY_ID], zwavejs=gateway
                    )

                self.assertEqual((cleared, failed), ([], []))
                self.assertFalse(any(c["method_name"] == "clear" for c in gateway.invoke_calls))
                self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=self.code), [])
                self.assertEqual(
                    lock_push_uc._unconfirmed_attempt_slots(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID),
                    [],
                )

    def test_inactive_tracked_slot_reading_passage_mode_is_forgotten_without_a_clear(self):
        DoorCode.objects.filter(id=self.code.id).update(is_active=False, push_state=DoorCode.PushState.PENDING)
        DoorCodeLockAssignment.objects.filter(door_code=self.code).update(slot_index=1)
        self.code.refresh_from_db()
        gateway = FakeGateway(usersNumber=3, get_responses=[{"userIdStatus": self.PASSAGE_MODE}] * 3)

        with patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)):
            still_failing = lock_push_uc.clear_inactive_code_slots(door_code=self.code, zwavejs=gateway)

        self.assertEqual(still_failing, [])
        self.assertFalse(any(c["method_name"] == "clear" for c in gateway.invoke_calls))
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=self.code).slot_index)


class PushInsideTransactionTests(EncryptionTestMixin, TestCase):
    """Issue #130: a push has to run in autocommit so its slot commits before the lock is let go."""

    LOCK_ENTITY_ID = "lock.front_door"

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )
        self.code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("1234"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID)

    def test_testcase_transaction_alone_does_not_count(self):
        from django.db import connection

        self.assertTrue(connection.in_atomic_block)
        gateway = FakeGateway(usersNumber=3)

        result = push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 1)

    def test_push_inside_a_caller_transaction_raises_in_tests_before_anything_is_sent(self):
        from django.db import transaction

        gateway = FakeGateway(usersNumber=3)

        with self.assertRaises(lock_push_uc.PushInTransaction), transaction.atomic():
            push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=self.code).slot_index)

    def test_push_inside_a_caller_transaction_warns_in_prod(self):
        from django.db import transaction
        from django.test import override_settings

        gateway = FakeGateway(usersNumber=3)

        with (
            override_settings(DEBUG=False, IS_TESTING=False),
            self.assertLogs(lock_push_uc.logger, level="WARNING") as logs,
            transaction.atomic(),
        ):
            result = push_door_code_to_lock(door_code=self.code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 1)
        self.assertTrue(any("inside an open DB transaction" in line for line in logs.output))


class PushWithAutocommitOffTests(EncryptionTestMixin, TransactionTestCase):
    """Issue #130 / PR #190 review: ``set_autocommit(False)`` leaves ``in_atomic_block`` false but still counts."""

    LOCK_ENTITY_ID = "lock.front_door"

    def test_push_with_autocommit_off_raises_before_anything_is_sent(self):
        from django.db import transaction

        user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )
        code = DoorCode.objects.create(
            user=user,
            encrypted_pin=SettingsEncryption.get().encrypt("1234"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        gateway = FakeGateway(usersNumber=3)

        transaction.set_autocommit(False)
        try:
            with self.assertRaises(lock_push_uc.PushInTransaction):
                push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        finally:
            transaction.rollback()
            transaction.set_autocommit(True)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=code).slot_index)


class TerminalPushErrorRecordingTests(EncryptionTestMixin, TestCase):
    """Issue #123: a bad stored PIN or window and a terminal Z-Wave JS error after the set are recorded."""

    LOCK_ENTITY_ID = "lock.front_door"
    MASKED = {"userIdStatus": 1, "userCode": "****"}

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )

    def _make_code(self, *, encrypted_pin: str | None = None, **kwargs) -> DoorCode:
        # Written straight to the DB, past the serializer's checks.
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=encrypted_pin if encrypted_pin is not None else SettingsEncryption.get().encrypt("1234"),
            pin_length=4,
            code_type=kwargs.pop("code_type", DoorCode.CodeType.PERMANENT),
            is_active=True,
            **kwargs,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        return code

    def _bad_window_code(self) -> DoorCode:
        return self._make_code(
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,
            window_start=time(17, 0),
            window_end=time(9, 0),
        )

    @staticmethod
    def _set_slots(gateway: FakeGateway) -> list[int]:
        return [c["args"][0] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == "set"]

    def _assert_terminal_failure_recorded(self, code: DoorCode, error: str) -> None:
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        # Counted on the lock; the code's own count only counts clear retries (issue #126).
        self.assertEqual(code.push_attempt_count, 0)
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual((assignment.push_state, assignment.push_attempt_count), (DoorCode.PushState.FAILED, 1))
        self.assertIsNotNone(code.last_push_attempt_at)
        self.assertIn(error, code.last_push_error)
        event = DoorCodeEvent.objects.get(door_code=code, metadata__action="push")
        self.assertEqual(event.event_type, DoorCodeEvent.EventType.CODE_FAILED)
        self.assertEqual(event.lock_entity_id, self.LOCK_ENTITY_ID)
        self.assertIn(error, event.metadata["reason"])

    def _markers(self, code: DoorCode) -> list[dict]:
        return list(
            DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed").values_list(
                "metadata", flat=True
            )
        )

    def test_bad_window_sends_no_set_and_is_recorded_as_a_terminal_failure(self):
        gateway = FakeGateway(usersNumber=3)
        code = self._bad_window_code()

        with self.assertRaises(InvalidPin):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(gateway.invoke_calls, [])
        self.assertEqual(gateway._lock_codes, {})
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=code).slot_index)
        self.assertEqual(self._markers(code), [])
        self._assert_terminal_failure_recorded(code, "window_end must be after window_start")

    def test_bad_window_ends_failed_and_the_scheduler_stops_pushing_it(self):
        from locks.tasks import push_pending_door_codes

        gateway = FakeGateway(usersNumber=3, drops_duplicates=False)
        code = self._bad_window_code()

        successes, failures = push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway)

        self.assertEqual(successes, [])
        self.assertEqual([lock for lock, _reason in failures], [self.LOCK_ENTITY_ID])
        self._assert_terminal_failure_recorded(code, "window_end must be after window_start")

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            self.assertEqual(push_pending_door_codes(), 0)
        self.assertEqual(self._set_slots(gateway), [])

    def test_undecryptable_pin_is_recorded_as_a_terminal_failure(self):
        gateway = FakeGateway(usersNumber=3)
        code = self._make_code(encrypted_pin="enc:v1:not-a-fernet-token")

        successes, failures = push_door_code_to_assigned_locks(door_code=code, zwavejs=gateway)

        self.assertEqual(successes, [])
        self.assertEqual(failures, [(self.LOCK_ENTITY_ID, "Stored PIN could not be decrypted.")])
        self.assertEqual(gateway.invoke_calls, [])
        self._assert_terminal_failure_recorded(code, "Stored PIN could not be decrypted.")

    def _terminal_error_after_the_set(self, *, during: str) -> tuple[DoorCode, FakeGateway]:
        from integrations_zwavejs.manager import ZwavejsClientUnavailable, ZwavejsCommandValidationError

        if during == "readback":
            # What reaches this path in prod: invoke_cc_api's own argument checks.
            message = "node_id must be a positive integer."
            gateway = FakeGateway(usersNumber=3, get_responses=[ZwavejsCommandValidationError(message)])
            code = self._make_code()
        else:
            message = "Z-Wave JS client library not installed."
            unavailable = ZwavejsClientUnavailable(message)

            class ScheduleFailsGateway(FakeGateway):
                def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                    if command_class == 78:
                        raise unavailable
                    return super().invoke_cc_api(
                        node_id=node_id,
                        command_class=command_class,
                        method_name=method_name,
                        args=args,
                        timeout_seconds=timeout_seconds,
                    )

            gateway = ScheduleFailsGateway(usersNumber=3)
            code = self._make_code(
                code_type=DoorCode.CodeType.TEMPORARY,
                days_of_week=0b1,
                window_start=time(9, 0),
                window_end=time(17, 0),
            )

        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        if during == "readback":
            self.assertIsNone(assignment.slot_index)
        else:
            # The PIN was confirmed before the schedule, so its slot is on record (issue #123).
            self.assertEqual((assignment.slot_index, assignment.schedule_pending), (1, True))
        self._assert_terminal_failure_recorded(code, message)
        return code, gateway

    def test_validation_error_during_the_readback_leaves_an_untagged_marker(self):
        code, _gateway = self._terminal_error_after_the_set(during="readback")

        [marker] = self._markers(code)
        self.assertEqual(marker["slot_index"], 1)
        # The readback never accepted the slot, so a masked readback later doesn't count as ours.
        self.assertNotIn("slot_verified", marker)

    def test_delete_after_validation_error_during_the_readback_reads_the_slot_back_and_clears_it(self):
        code, gateway = self._terminal_error_after_the_set(during="readback")
        gateway.invoke_calls.clear()

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        cc99 = [(c["method_name"], c["args"]) for c in gateway.invoke_calls if c["command_class"] == 99]
        self.assertEqual(cc99, [("get", [1]), ("clear", [1])])
        self.assertEqual(gateway._lock_codes, {})

    def test_retry_after_validation_error_during_the_readback_adopts_the_slot(self):
        # On a lock that takes duplicates, a retry without the marker puts the PIN in a second slot.
        code, gateway = self._terminal_error_after_the_set(during="readback")
        gateway._drops_duplicates = False

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 1)
        self.assertEqual(self._set_slots(gateway), [1])
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})

    def test_client_unavailable_during_the_schedule_push_keeps_the_slot_failed_with_its_schedule_pending(self):
        # Issue #123: the slot is tracked before the schedule goes out, so no
        # marker is needed and the lock is failed with the slot kept.
        code, _gateway = self._terminal_error_after_the_set(during="schedule")

        self.assertEqual(self._markers(code), [])
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(
            (assignment.slot_index, assignment.push_state, assignment.schedule_pending),
            (1, DoorCode.PushState.FAILED, True),
        )
        self.assertIn("Schedule not applied", assignment.last_push_error)

    def test_delete_after_client_unavailable_during_the_schedule_push_clears_the_slot(self):
        for masked in (False, True):
            with self.subTest(masked=masked):
                code, gateway = self._terminal_error_after_the_set(during="schedule")
                if masked:
                    gateway._get_scripts = {None: [self.MASKED] * 20}

                door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

                self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
                self.assertEqual(gateway._lock_codes, {})

    def test_terminal_error_from_the_set_itself_leaves_no_marker(self):
        # These errors are raised before anything is sent, so the PIN never went out.
        from integrations_zwavejs.manager import ZwavejsCommandValidationError

        gateway = FakeGateway(
            usersNumber=3, invoke_raises=ZwavejsCommandValidationError("bad args"), invoke_raises_after=0
        )
        code = self._make_code()

        with self.assertRaises(LockPushFailed):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(self._markers(code), [])
        self._assert_terminal_failure_recorded(code, "bad args")

    @staticmethod
    def _schedule_times_out_gateway(**kwargs) -> FakeGateway:
        from integrations_zwavejs.manager import ZwavejsCommandError

        class ScheduleTimesOutGateway(FakeGateway):
            def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
                if command_class == 78:
                    raise ZwavejsCommandError("driver TimeoutError after 5.0s")
                return super().invoke_cc_api(
                    node_id=node_id,
                    command_class=command_class,
                    method_name=method_name,
                    args=args,
                    timeout_seconds=timeout_seconds,
                )

        return ScheduleTimesOutGateway(**kwargs)

    def _scheduled_code(self) -> DoorCode:
        return self._make_code(
            code_type=DoorCode.CodeType.TEMPORARY,
            days_of_week=0b1,
            window_start=time(9, 0),
            window_end=time(17, 0),
        )

    def _newest_marker(self, code: DoorCode) -> dict:
        return (
            DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed")
            .order_by("-id")
            .values_list("metadata", flat=True)
            .first()
        )

    def test_masked_lock_schedule_timeout_after_the_readback_keeps_the_slot_and_a_delete_clears(self):
        # Issue #123: the slot is tracked before the schedule, so even on a lock
        # that masks PINs the delete clears it without a readback.
        gateway = self._schedule_times_out_gateway(usersNumber=3, get_responses=[self.MASKED] * 20)
        code = self._scheduled_code()

        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
        self.assertEqual(self._markers(code), [])
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual(
            (assignment.slot_index, assignment.push_state, assignment.schedule_pending, assignment.push_attempt_count),
            (1, DoorCode.PushState.PENDING, True, 1),
        )
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(gateway._lock_codes, {})

    def test_readback_timeout_leaves_an_untagged_marker(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway = FakeGateway(usersNumber=3, get_responses=[timeout, timeout, timeout])
        code = self._make_code()

        with (
            patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)),
            self.assertRaises(LockUnreachable),
        ):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertNotIn("slot_verified", self._newest_marker(code))

    def test_adopted_tagged_slot_is_tracked_with_its_schedule_pending_after_a_schedule_timeout(self):
        code = self._scheduled_code()
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            slot_index=1,
            reason="PIN set on the lock, slot not saved yet",
            pin="1234",
            slot_verified=True,
        )
        gateway = self._schedule_times_out_gateway(usersNumber=3, get_responses=[self.MASKED] * 20)
        gateway._lock_codes[(7, 1)] = "1234"

        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(self._set_slots(gateway), [])
        # The adopted slot is tracked before the schedule now (issue #123), so the
        # only marker is the one adopted, and the slot waits on its schedule.
        self.assertEqual(len(self._markers(code)), 1)
        assignment = DoorCodeLockAssignment.objects.get(door_code=code)
        self.assertEqual((assignment.slot_index, assignment.schedule_pending), (1, True))

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(gateway._lock_codes, {})

    def test_masked_slot_read_back_empty_before_a_fresh_set_isnt_ours_once_a_keypad_code_lands(self):
        # PR #192 review: a fresh set only goes into the slot of an older tagged
        # attempt after adoption read that slot back empty, which disproves the
        # old tag, so the new attempt must stay untagged.
        from integrations_zwavejs.manager import ZwavejsCommandError

        # A schedule timeout keeps the slot tracked since issue #123, so the tagged
        # attempt this starts from is #190's rolled back success marker.
        gateway = self._schedule_times_out_gateway(usersNumber=3)
        code = self._scheduled_code()
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code,
            lock_entity_id=self.LOCK_ENTITY_ID,
            slot_index=1,
            reason="PIN set on the lock, slot not saved yet",
            pin="1234",
            slot_verified=True,
        )
        self.assertIs(self._newest_marker(code)["slot_verified"], True)

        # The PIN isn't in the slot, so the push reads it back empty twice, writes
        # the PIN there again, the lock drops it and the readback times out.
        gateway._reject_pins = {7: {"1234"}}
        empty = {"userIdStatus": 0, "userCode": ""}
        timeout = ZwavejsCommandError("driver TimeoutError after 5.0s")
        gateway._get_scripts = {None: [empty, empty, timeout, timeout, timeout]}
        with (
            patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0)),
            self.assertRaises(LockUnreachable),
        ):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertEqual(self._set_slots(gateway), [1])
        self.assertNotIn("slot_verified", self._newest_marker(code))

        # Someone types a keypad code into that slot, and the lock masks it.
        gateway._lock_codes[(7, 1)] = "9999"
        gateway._get_scripts = {None: [self.MASKED] * 20}

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})
        self.assertFalse(any(c["method_name"] == "clear" for c in gateway.invoke_calls))


class _ClaimDuringReadbackGateway(FakeGateway):
    """A FakeGateway that runs ``claim_on_get`` once, on the next CC 99 ``get``, before answering it."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.claim_on_get = None

    def _handle_user_code_call(self, *, node_id: int, method_name: str, args: list):
        if method_name == "get" and self.claim_on_get is not None:
            claim, self.claim_on_get = self.claim_on_get, None
            claim()
        return super()._handle_user_code_call(node_id=node_id, method_name=method_name, args=args)


class MaskedUnconfirmedSlotTests(EncryptionTestMixin, TestCase):
    """Issues #128 and #152: a masked unconfirmed slot that was Available when the push picked it is ours."""

    LOCK_ENTITY_ID = "lock.front_door"
    MASKED = {"userIdStatus": 1, "userCode": "****"}
    EMPTY = {"userIdStatus": 0, "userCode": ""}

    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        Entity.objects.create(
            entity_id=self.LOCK_ENTITY_ID,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 7}},
            source="home_assistant",
        )
        patcher = patch.object(lock_push_uc, "_READBACK_RETRY_DELAYS_SECONDS", (0.0, 0.0))
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _timeouts(count: int = 3) -> list[Exception]:
        from integrations_zwavejs.manager import ZwavejsCommandError

        return [ZwavejsCommandError("driver TimeoutError after 5.0s") for _ in range(count)]

    def _make_code(self, *, pin: str = "1234") -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)
        return code

    def _unconfirmed_push(
        self, *, gateway_class: type[FakeGateway] = FakeGateway, drops_duplicates: bool = True
    ) -> tuple[DoorCode, FakeGateway]:
        """Push 1234 to a lock that masks codes: it lands in slot 1, its readbacks time out, then gets answer masked."""
        gateway = gateway_class(
            usersNumber=3,
            cache_updates_on_set=True,
            drops_duplicates=drops_duplicates,
            get_responses=self._timeouts(),
        )
        code = self._make_code()
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
        self.assertIsNone(self._slot_of(code))
        gateway._get_scripts = {None: [self.MASKED] * 20}
        gateway.invoke_calls.clear()
        return code, gateway

    def _slot_of(self, code: DoorCode) -> int | None:
        return DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID).slot_index

    @staticmethod
    def _calls(gateway: FakeGateway, method_name: str) -> list[int]:
        return [
            c["args"][0] for c in gateway.invoke_calls if c["command_class"] == 99 and c["method_name"] == method_name
        ]

    @staticmethod
    def _newest_marker(code: DoorCode) -> dict:
        return (
            DoorCodeEvent.objects.filter(door_code=code, metadata__action="push_unconfirmed")
            .order_by("-id")
            .values_list("metadata", flat=True)
            .first()
        )

    def _push_ignoring_failure(self, code: DoorCode, gateway: FakeGateway) -> None:
        with contextlib.suppress(LockPushFailed, LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

    def test_a_readback_timeout_after_a_set_into_an_available_slot_is_tagged(self):
        code, _gateway = self._unconfirmed_push()

        marker = self._newest_marker(code)
        self.assertIs(marker["slot_available"], True)
        self.assertNotIn("slot_verified", marker)

    def test_pin_change_clears_the_old_pin_from_the_masked_slot(self):
        # Issue #152: the cleanup used to settle the masked slot as not holding the
        # PIN, so 1234 stayed in slot 1 and the code showed pushed.
        code, gateway = self._unconfirmed_push()

        door_codes_uc.update_door_code(code=code, changes={"code": "5678"}, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [1])
        self.assertEqual(gateway._lock_codes, {(7, 1): "5678"})
        self.assertEqual(self._slot_of(code), 1)
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_pin_change_whose_clear_times_out_stays_pending_until_the_retry_clears_it(self):
        from locks.tasks import push_pending_door_codes

        code, gateway = self._unconfirmed_push(gateway_class=ClearFailingGateway)
        gateway.clear_fails_on = {7}

        door_codes_uc.update_door_code(code=code, changes={"code": "5678"}, zwavejs=gateway)

        self.assertEqual(gateway._lock_codes, {(7, 1): "1234", (7, 2): "5678"})
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertEqual((failure.slot_index, failure.unconfirmed, failure.slot_available), (1, True, True))
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PENDING)

        gateway.clear_fails_on = set()
        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        self.assertEqual(gateway._lock_codes, {(7, 2): "5678"})
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_delete_clears_the_masked_slot(self):
        for drops_duplicates in (True, False):
            with self.subTest(drops_duplicates=drops_duplicates):
                code, gateway = self._unconfirmed_push(drops_duplicates=drops_duplicates)

                door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

                self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
                self.assertEqual(self._calls(gateway, "clear"), [1])
                self.assertEqual(gateway._lock_codes, {})

    def test_delete_after_a_pin_change_whose_clear_timed_out_clears_the_old_slot(self):
        code, gateway = self._unconfirmed_push(gateway_class=ClearFailingGateway)
        gateway.clear_fails_on = {7}
        door_codes_uc.update_door_code(code=code, changes={"code": "5678"}, zwavejs=gateway)
        gateway.clear_fails_on = set()

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(gateway._lock_codes, {})

    def test_retry_resends_into_the_attempted_slot_instead_of_a_second_one(self):
        # Issue #128: the retry used to write the PIN to slot 2, which a lock that
        # drops duplicates rejects, leaving slot 1 working with nothing tracking it.
        for drops_duplicates in (True, False):
            with self.subTest(drops_duplicates=drops_duplicates):
                code, gateway = self._unconfirmed_push(drops_duplicates=drops_duplicates)

                result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

                self.assertEqual(result.slot_index, 1)
                self.assertEqual(self._calls(gateway, "set"), [1])
                self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
                self.assertEqual(self._slot_of(code), 1)
                code.refresh_from_db()
                self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)
                pushed = DoorCodeEvent.objects.get(door_code=code, metadata__action="pushed")
                self.assertIs(pushed.metadata["resent_to_attempted_slot"], True)

                door_codes_uc.delete_door_code(code=code, zwavejs=gateway)
                self.assertEqual(gateway._lock_codes, {})

    def test_a_resend_answered_with_supervision_fail_keeps_the_slot_tagged_so_a_delete_clears_it(self):
        # PR #198 review: an untagged Fail marker on top of the slot_available
        # attempt made the delete leave 1234 in slot 1, and Retry then used slot 2.
        code, gateway = self._unconfirmed_push()
        gateway._set_result = {"status": 2}

        with self.assertRaises(LockRejectedCode):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        # Adoption read it back masked and resent, and the lock answered Fail.
        self.assertEqual(self._calls(gateway, "set"), [1])
        self.assertEqual(self._calls(gateway, "get"), [1])
        self.assertIsNone(self._slot_of(code))
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
        marker = self._newest_marker(code)

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._calls(gateway, "clear"), [1])
        self.assertEqual(gateway._lock_codes, {})
        # The Fail marker kept the resend target's slot_available tag.
        self.assertEqual((marker.get("slot_available"), marker.get("slot_verified")), (True, None))

    def test_a_resend_answered_with_supervision_fail_is_resent_again_on_retry(self):
        code, gateway = self._unconfirmed_push()
        gateway._set_result = {"status": 2}
        with self.assertRaises(LockRejectedCode):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        gateway._set_result = None
        gateway.invoke_calls.clear()
        admin = User.objects.create_superuser(email="admin@example.com", password="pass")

        door_codes_uc.retry_push_door_code(code=code, actor_user=admin, zwavejs=gateway)

        # Into slot 1 again, not a second slot a lock that drops duplicates rejects.
        self.assertEqual(self._calls(gateway, "set"), [1])
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234"})
        self.assertEqual(self._slot_of(code), 1)
        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.PUSHED)

    def test_a_resend_whose_readback_times_out_again_stays_tagged(self):
        code, gateway = self._unconfirmed_push()
        gateway._get_scripts = {None: [self.MASKED, *self._timeouts()]}

        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "set"), [1])
        self.assertIs(self._newest_marker(code)["slot_available"], True)

    def test_a_readable_different_code_a_config_slot_or_an_empty_slot_is_never_ours(self):
        for name, response in (
            ("different code", {"userIdStatus": 1, "userCode": "9999"}),
            ("messaging", {"userIdStatus": 3}),
            ("passage mode", {"userIdStatus": 4}),
            ("empty", self.EMPTY),
        ):
            for operation in ("delete", "retry"):
                with self.subTest(readback=name, operation=operation):
                    code, gateway = self._unconfirmed_push()
                    gateway._lock_codes[(7, 1)] = "9999"
                    gateway._get_scripts = {None: [response] * 20}

                    if operation == "delete":
                        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)
                        self.assertEqual(self._calls(gateway, "clear"), [])
                    else:
                        self._push_ignoring_failure(code, gateway)
                        self.assertNotIn(1, self._calls(gateway, "set"))
                        DoorCode.objects.filter(id=code.id).delete()
                    self.assertEqual(gateway._lock_codes.get((7, 1)), "9999")

    def test_a_slot_another_code_takes_during_the_readback_is_left_alone(self):
        for operation in ("delete", "retry"):
            with self.subTest(operation=operation):
                code, gateway = self._unconfirmed_push(
                    gateway_class=_ClaimDuringReadbackGateway, drops_duplicates=False
                )
                other = self._make_code(pin="9999")
                gateway.claim_on_get = lambda other=other: DoorCodeLockAssignment.objects.filter(
                    door_code=other
                ).update(slot_index=1)

                if operation == "delete":
                    door_codes_uc.delete_door_code(code=code, zwavejs=gateway)
                    self.assertEqual(self._calls(gateway, "clear"), [])
                else:
                    self._push_ignoring_failure(code, gateway)
                    self.assertNotIn(1, self._calls(gateway, "set"))
                    DoorCode.objects.filter(id=code.id).delete()
                self.assertEqual(self._slot_of(other), 1)
                self.assertEqual(gateway._lock_codes.get((7, 1)), "1234")
                DoorCode.objects.filter(id=other.id).delete()

    def test_a_readback_that_answered_empty_once_isnt_tagged(self):
        gateway = FakeGateway(usersNumber=3, cache_updates_on_set=True, get_responses=[self.EMPTY, *self._timeouts(2)])
        code = self._make_code()
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertNotIn("slot_available", self._newest_marker(code))

        # The set may never have landed, so a masked code typed in there later isn't ours.
        gateway._lock_codes[(7, 1)] = "9999"
        gateway._get_scripts = {None: [self.MASKED] * 20}
        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    def _disproved_attempt(self) -> tuple[DoorCode, FakeGateway]:
        """PR #192's scenario on an untagged attempt: slot 1 reads back empty, then the PIN's resend there is lost.

        The PIN leaves slot 1, the retry reads it back empty twice, writes the
        PIN there again, the lock drops it and the readback times out. Then
        someone types a keypad code into slot 1, and the lock masks it.
        """
        code, gateway = self._unconfirmed_push()
        gateway._lock_codes.clear()
        gateway._cache_codes.clear()
        gateway._reject_pins = {7: {"1234"}}
        gateway._get_scripts = {None: [self.EMPTY, self.EMPTY, *self._timeouts()]}
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "set"), [1])
        self.assertNotIn("slot_available", self._newest_marker(code))

        gateway._reject_pins = {}
        gateway._lock_codes[(7, 1)] = "9999"
        gateway._cache_codes[(7, 1)] = "9999"
        gateway._get_scripts = {None: [self.MASKED] * 20}
        gateway.invoke_calls.clear()
        return code, gateway

    def test_a_slot_read_back_empty_after_the_attempt_isnt_cleared_once_a_keypad_code_lands(self):
        code, gateway = self._disproved_attempt()

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    def test_a_slot_read_back_empty_after_the_attempt_isnt_resent_to_once_a_keypad_code_lands(self):
        code, gateway = self._disproved_attempt()

        self._push_ignoring_failure(code, gateway)

        self.assertNotIn(1, self._calls(gateway, "set"))
        self.assertEqual(gateway._lock_codes[(7, 1)], "9999")

    def test_the_clear_retry_counts_a_masked_slot_as_ours_only_for_a_tagged_unconfirmed_failure(self):
        # PR #190 review: the retry gate in _retry_failed_slot_clear had no test pinning it down.
        from integrations_zwavejs.manager import ZwavejsCommandError

        cases = {
            "unconfirmed, untagged": ({"unconfirmed": True}, False),
            "unconfirmed, slot_available": ({"unconfirmed": True, "slot_available": True}, True),
            "unconfirmed, slot_verified": ({"unconfirmed": True, "slot_verified": True}, True),
            "a tracked slot's, no longer tracked": ({"slot_available": True}, False),
        }
        for name, (flags, cleared) in cases.items():
            with self.subTest(failure=name):
                code = self._make_code()
                lock_push_uc.record_clear_failure(
                    door_code=code,
                    lock_entity_id=self.LOCK_ENTITY_ID,
                    slot_index=1,
                    exc=ZwavejsCommandError("driver TimeoutError after 5.0s"),
                    expected_pin="1234",
                    **flags,
                )
                gateway = FakeGateway(usersNumber=3, get_responses=[self.MASKED] * 20)
                gateway._lock_codes[(7, 1)] = "9999"

                still_failing = lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)

                self.assertEqual(still_failing, [])
                self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])
                if cleared:
                    self.assertEqual(self._calls(gateway, "clear"), [1])
                    self.assertEqual(gateway._lock_codes, {})
                else:
                    self.assertEqual(self._calls(gateway, "clear"), [])
                    self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})
                DoorCode.objects.filter(id=code.id).delete()

    def test_a_resend_only_goes_into_an_attempt_that_sent_the_current_pin(self):
        # The attempt sent 1234 and the code's PIN is 5678 now, so slot 1 may hold the old PIN.
        code, gateway = self._unconfirmed_push(drops_duplicates=False)
        DoorCode.objects.filter(id=code.id).update(encrypted_pin=SettingsEncryption.get().encrypt("5678"))

        result = push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)

        self.assertEqual(result.slot_index, 2)
        self.assertEqual(self._calls(gateway, "set"), [2])
        self.assertEqual(gateway._lock_codes, {(7, 1): "1234", (7, 2): "5678"})

    def _keypad_code_lands_in_slot_1(self, gateway: FakeGateway) -> None:
        gateway._lock_codes[(7, 1)] = "9999"
        gateway._cache_codes[(7, 1)] = "9999"
        gateway._get_scripts = {None: [self.MASKED] * 20}
        gateway.invoke_calls.clear()

    def _adoption_reads_empty_once_then_times_out(self) -> tuple[DoorCode, FakeGateway]:
        """PR #193 review P1: the retry's adoption readback answers empty once, then gets no answer."""
        code, gateway = self._unconfirmed_push()
        gateway._lock_codes.clear()
        gateway._get_scripts = {None: [self.EMPTY, *self._timeouts(2)]}
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "set"), [])
        self._keypad_code_lands_in_slot_1(gateway)
        return code, gateway

    def test_a_retry_doesnt_resend_over_a_keypad_code_after_adoption_saw_the_slot_empty_once(self):
        code, gateway = self._adoption_reads_empty_once_then_times_out()

        self._push_ignoring_failure(code, gateway)

        self.assertNotIn(1, self._calls(gateway, "set"))
        self.assertEqual(gateway._lock_codes[(7, 1)], "9999")

    def test_a_delete_doesnt_clear_a_keypad_code_after_adoption_saw_the_slot_empty_once(self):
        code, gateway = self._adoption_reads_empty_once_then_times_out()

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    def test_a_slot_seen_empty_once_still_gets_its_readable_pin_cleared(self):
        # The marker settles nothing, so a lock that shows codes still gets the PIN taken off.
        code, gateway = self._unconfirmed_push()
        gateway._get_scripts = {None: [self.EMPTY, *self._timeouts(2)]}
        with self.assertRaises(LockUnreachable):
            push_door_code_to_lock(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        gateway._get_scripts = {None: []}

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(gateway._lock_codes, {})

    def test_a_clear_retry_leaves_a_keypad_code_after_the_cleanup_saw_the_slot_empty_once(self):
        # PR #193 review P2: the PIN change's cleanup readback answers empty once, then gets no answer.
        code, gateway = self._unconfirmed_push()
        del gateway._lock_codes[(7, 1)]  # the Z-Wave JS cache still says slot 1 is taken
        gateway._get_scripts = {None: [self.EMPTY, *self._timeouts(2), *[self.MASKED] * 20]}

        door_codes_uc.update_door_code(code=code, changes={"code": "5678"}, zwavejs=gateway)

        [failure] = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertEqual((failure.slot_index, failure.slot_available, failure.slot_verified), (1, False, False))
        self.assertEqual(self._slot_of(code), 2)
        self._keypad_code_lands_in_slot_1(gateway)

        lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes[(7, 1)], "9999")
        self.assertEqual(lock_push_uc.unresolved_clear_failures(door_code=code), [])

    def test_a_clear_retry_leaves_a_keypad_code_after_an_earlier_retry_saw_the_slot_empty_once(self):
        code, gateway = self._unconfirmed_push(gateway_class=ClearFailingGateway)
        gateway.clear_fails_on = {7}
        door_codes_uc.update_door_code(code=code, changes={"code": "5678"}, zwavejs=gateway)
        [failure] = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertIs(failure.slot_available, True)
        gateway.clear_fails_on = set()
        del gateway._lock_codes[(7, 1)]
        gateway._get_scripts = {None: [self.EMPTY, *self._timeouts(2)]}

        self.assertEqual(len(lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)), 1)
        self._keypad_code_lands_in_slot_1(gateway)
        lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes[(7, 1)], "9999")

    def test_a_disabled_masked_slot_isnt_ours_for_an_attempt_nothing_confirmed(self):
        # PR #193 review P3: we always send the code enabled, so a disabled one may be someone else's.
        code, gateway = self._unconfirmed_push()
        gateway._lock_codes[(7, 1)] = "9999"
        gateway._get_scripts = {None: [{"userIdStatus": 2, "userCode": "****"}] * 20}

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    def test_another_codes_readback_seeing_the_slot_empty_drops_the_trust(self):
        # X's set into slot 1 never stuck. Y's push picks slot 1 too and reads it back
        # empty twice, then someone types a keypad code in there.
        code, gateway = self._unconfirmed_push()
        gateway._lock_codes.clear()
        gateway._cache_codes.clear()
        other = self._make_code(pin="5555")
        gateway._reject_pins = {7: {"5555"}}
        gateway._get_scripts = {None: [self.EMPTY, self.EMPTY]}
        with self.assertRaises(LockRejectedCode):
            push_door_code_to_lock(door_code=other, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "set"), [1])
        gateway._reject_pins = {}
        self._keypad_code_lands_in_slot_1(gateway)

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    @staticmethod
    def _prune_old_events() -> None:
        """Age every event past a 90 day retention and run the retention task."""
        from django.utils import timezone

        from locks.tasks import cleanup_door_code_events

        DoorCodeEvent.objects.update(created_at=timezone.now() - timedelta(days=100))
        with patch("locks.tasks._get_door_code_event_retention_days", return_value=90):
            cleanup_door_code_events()

    def test_pruning_doesnt_bring_back_the_trust_adoption_dropped(self):
        # PR #193 re-review R1.
        code, gateway = self._adoption_reads_empty_once_then_times_out()
        self._prune_old_events()

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    def test_pruning_doesnt_bring_back_the_trust_a_clear_retry_dropped(self):
        # PR #193 re-review R2.
        code, gateway = self._unconfirmed_push(gateway_class=ClearFailingGateway)
        gateway.clear_fails_on = {7}
        door_codes_uc.update_door_code(code=code, changes={"code": "5678"}, zwavejs=gateway)
        gateway.clear_fails_on = set()
        del gateway._lock_codes[(7, 1)]
        gateway._get_scripts = {None: [self.EMPTY, *self._timeouts(2)]}
        self.assertEqual(len(lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)), 1)
        self._keypad_code_lands_in_slot_1(gateway)

        self._prune_old_events()

        [failure] = lock_push_uc.unresolved_clear_failures(door_code=code)
        self.assertEqual((failure.slot_index, failure.slot_available), (1, False))
        lock_push_uc.retry_failed_slot_clears(door_code=code, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes[(7, 1)], "9999")

    def _other_code_reads_slot_1(
        self, *, get_responses: list, expected_error: type[Exception]
    ) -> tuple[DoorCode, FakeGateway]:
        """X's set into slot 1 never stuck. Y's push picks slot 1 too, its set is dropped and its readback runs."""
        code, gateway = self._unconfirmed_push()
        gateway._lock_codes.clear()
        gateway._cache_codes.clear()
        other = self._make_code(pin="5555")
        gateway._reject_pins = {7: {"5555"}}
        gateway._get_scripts = {None: list(get_responses)}
        with self.assertRaises(expected_error):
            push_door_code_to_lock(door_code=other, lock_entity_id=self.LOCK_ENTITY_ID, zwavejs=gateway)
        self.assertEqual(self._calls(gateway, "set"), [1])
        gateway._reject_pins = {}
        self._keypad_code_lands_in_slot_1(gateway)
        return code, gateway

    def test_pruning_keeps_another_codes_marker_that_dropped_the_trust(self):
        code, gateway = self._other_code_reads_slot_1(
            get_responses=[self.EMPTY, self.EMPTY], expected_error=LockRejectedCode
        )
        self._prune_old_events()

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    def test_another_codes_post_set_readback_seeing_the_slot_empty_once_drops_the_trust(self):
        code, gateway = self._other_code_reads_slot_1(
            get_responses=[self.EMPTY, *self._timeouts(2)], expected_error=LockUnreachable
        )

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes, {(7, 1): "9999"})

    def test_another_codes_cleanup_seeing_the_slot_empty_once_drops_the_trust(self):
        # X's attempt on slot 1 is tagged. Y also has an attempt there, and Y's PIN
        # change cleanup reads slot 1 back empty once, then gets no answer.
        code, gateway = self._unconfirmed_push()
        del gateway._lock_codes[(7, 1)]  # the Z-Wave JS cache still says slot 1 is taken
        other = self._make_code(pin="5555")
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=other, lock_entity_id=self.LOCK_ENTITY_ID, slot_index=1, reason="timeout", pin="5555"
        )
        gateway._get_scripts = {None: [self.EMPTY, *self._timeouts(2), *[self.MASKED] * 20]}
        door_codes_uc.update_door_code(code=other, changes={"code": "6666"}, zwavejs=gateway)
        self.assertEqual(self._slot_of(other), 2)
        self._keypad_code_lands_in_slot_1(gateway)

        door_codes_uc.delete_door_code(code=code, zwavejs=gateway)

        self.assertEqual(self._calls(gateway, "clear"), [])
        self.assertEqual(gateway._lock_codes[(7, 1)], "9999")
