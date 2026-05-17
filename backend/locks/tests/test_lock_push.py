"""Tests for ADR 0092 push_door_code_to_lock."""

from __future__ import annotations

import json
from datetime import time
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
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
        self.assertEqual(set_calls[0]["args"], [2, "1234"])

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
            payload = call["args"][0]
            self.assertEqual(payload["userId"], result.slot_index)
            self.assertEqual(payload["startHour"], 9)
            self.assertEqual(payload["startMinute"], 0)
            self.assertEqual(payload["durationHour"], 8)
            self.assertEqual(payload["durationMinute"], 30)
            self.assertEqual(len(payload["weekdays"]), 1)
            self.assertIn(payload["weekdays"][0], (1, 3))

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

    def test_pin_redacted_in_invoke_cc_api_debug_log(self):
        """ADR 0092 §7: PIN bytes must never reach DEBUG logs."""
        from integrations_zwavejs.manager import _redact_cc_api_args_for_log

        redacted = _redact_cc_api_args_for_log(command_class=99, method_name="set", args=[3, "9876"])
        self.assertEqual(redacted, [3, "***"])

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
        # PIN reached the gateway args (the redaction is log-only).
        self.assertEqual(set_calls[0]["args"][1], "2468")

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
