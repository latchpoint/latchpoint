"""Tests for ADR 0092 push_door_code_to_lock."""

from __future__ import annotations

import json
from datetime import time
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
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
    """

    def __init__(
        self,
        *,
        usersNumber: int = 5,
        slot_status: dict[int, int] | None = None,
        invoke_raises: Exception | None = None,
        invoke_raises_after: int | None = None,
        admin_code: str | None = None,
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

    def deliver_late_reports(self) -> None:
        """Apply queued user-code reports to the value cache."""
        for node_id, slot, code in self._late_reports:
            self._cache_codes[(node_id, slot)] = code
        self._late_reports = []

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0):  # noqa: ARG002
        value_ids = [{"commandClass": 99, "property": "usersNumber"}]
        if self._admin_code is not None:
            value_ids.append({"commandClass": 99, "property": "adminCode"})
        for slot in range(1, self._usersNumber + 1):
            value_ids.append({"commandClass": 99, "property": "userIdStatus", "propertyKey": slot})
            value_ids.append({"commandClass": 99, "property": "userCode", "propertyKey": slot})
        return value_ids

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0):  # noqa: ARG002
        if value_id.get("property") == "usersNumber":
            return self._usersNumber
        if value_id.get("property") == "adminCode":
            return self._admin_code
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
            if pin in self._reject_pins.get(node_id, set()) or held_elsewhere:
                return None  # the lock silently drops it; the set still "succeeds"
            self._lock_codes[(node_id, slot)] = pin
            if self._cache_updates_on_set:
                self._cache_codes[(node_id, slot)] = pin
            else:
                self._late_reports.append((node_id, slot, pin))
            return None
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
        timeout_seconds: float = 10.0,  # noqa: ARG002
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

        event = DoorCodeEvent.objects.get(door_code=code)
        self.assertTrue(event.metadata.get("schedule_applied"))

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
        # Start the row 1 tick away from the 24-attempt cap so this tick trips it.
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin=SettingsEncryption.get().encrypt("2222"),
            pin_length=4,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=True,
            push_state=DoorCode.PushState.PENDING,
            push_attempt_count=23,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK_ENTITY_ID)

        with patch("locks.tasks.default_zwavejs_gateway", gateway):
            push_pending_door_codes()

        code.refresh_from_db()
        self.assertEqual(code.push_state, DoorCode.PushState.FAILED)
        self.assertGreaterEqual(code.push_attempt_count, 24)
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
        self.assertEqual(code.push_attempt_count, 1)
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=code).slot_index)
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
        self.assertEqual(code.push_attempt_count, 1)
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=code).slot_index)
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

    def test_pin_matching_admin_code_fails_before_any_set(self):
        gateway = FakeGateway(usersNumber=3, slot_status={1: 0, 2: 0, 3: 0}, admin_code="4321")
        code = self._make_code(pin="4321")

        with self.assertRaises(LockRejectedCode) as ctx:
            self._push(code, gateway)

        self.assertIn("admin code", str(ctx.exception))
        self.assertEqual(gateway.invoke_calls, [])
        self._assert_terminal_failure(code, error_contains="PIN matches this lock's admin code")

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
        # First tick fails it terminally, the second tick skips the failed row.
        self.assertEqual(code.push_attempt_count, 1)


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
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
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
        synced = DoorCodeEvent.objects.get(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED)
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
            [{"lock_entity_id": self.LOCK_ENTITY_ID, "slot_index": 7}],
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

        self.assertEqual(data["lock_slot_assignments"], [{"lock_entity_id": self.LOCK_ENTITY_ID, "slot_index": None}])

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
