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
from locks.use_cases.lock_push import (
    InvalidPin,
    LockPushFailed,
    LockSlotsFull,
    LockUnreachable,
    push_door_code_to_lock,
    sanitize_push_error_for_storage,
)


def _value_id_key(value_id: dict) -> str:
    return f"{value_id.get('commandClass')}:{value_id.get('property')}:{value_id.get('propertyKey')}"


class FakeGateway:
    """Records invoke_cc_api calls and serves canned slot reads from a script."""

    def __init__(
        self,
        *,
        usersNumber: int = 5,
        slot_status: dict[int, int] | None = None,
        invoke_raises: Exception | None = None,
        invoke_raises_after: int | None = None,
    ):
        self._usersNumber = usersNumber
        self._slot_status = slot_status or {}
        self._invoke_raises = invoke_raises
        self._invoke_raises_after = invoke_raises_after
        self.invoke_calls: list[dict] = []

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0):  # noqa: ARG002
        value_ids = [{"commandClass": 99, "property": "usersNumber"}]
        for slot in range(1, self._usersNumber + 1):
            value_ids.append({"commandClass": 99, "property": "userIdStatus", "propertyKey": slot})
        return value_ids

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0):  # noqa: ARG002
        if value_id.get("property") == "usersNumber":
            return self._usersNumber
        if value_id.get("property") == "userIdStatus":
            return self._slot_status.get(int(value_id.get("propertyKey")), 0)
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
