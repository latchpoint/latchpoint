from __future__ import annotations

import importlib
import json
from unittest import TestCase
from unittest.mock import patch

from django.db.models.signals import post_save
from django.test import TestCase as DjangoTestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.crypto import SettingsEncryption
from alarm.models import AlarmSettingsEntry, Entity
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.tests.settings_test_utils import EncryptionTestMixin
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment
from locks.use_cases import door_codes as door_codes_uc
from locks.use_cases import lock_push as lock_push_uc
from locks.use_cases.lock_config_sync import _is_confirmed_empty_status, _normalize_pin, _weekday_to_mask_index


class WeekdayToMaskIndexTests(TestCase):
    """CC 78 ScheduleEntryLockWeekday (Sunday=0..Saturday=6) -> mask bit (Mon=0..Sun=6)."""

    def test_cc78_sunday_zero_maps_to_sunday_bit(self):
        # The round-trip bug: ZW 0 = Sunday, must decode to bit 6 (not Monday/bit 0).
        self.assertEqual(_weekday_to_mask_index(0), 6)

    def test_monday_through_saturday(self):
        self.assertEqual(_weekday_to_mask_index(1), 0)  # Monday
        self.assertEqual(_weekday_to_mask_index(2), 1)
        self.assertEqual(_weekday_to_mask_index(6), 5)  # Saturday

    def test_legacy_seven_still_maps_to_sunday(self):
        # Some sources use 1=Monday..7=Sunday; 7 must also land on the Sunday bit.
        self.assertEqual(_weekday_to_mask_index(7), 6)

    def test_out_of_range_returns_none(self):
        self.assertIsNone(_weekday_to_mask_index(8))
        self.assertIsNone(_weekday_to_mask_index(-1))


class FakeZwavejsGateway:
    def __init__(
        self,
        *,
        value_ids: list[dict],
        values: dict[tuple[int, str], object],
        cc_api_responses: dict[tuple[int, int, str, str], object] | None = None,
    ):
        self._value_ids = value_ids
        self._values = values
        self._cc_api_responses = cc_api_responses or {}

    def apply_settings(self, *, settings_obj):  # noqa: ARG002
        return None

    def ensure_connected(self, *, timeout_seconds: float = 5.0):  # noqa: ARG002
        return None

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0):  # noqa: ARG002
        return list(self._value_ids)

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0):  # noqa: ARG002
        key = (int(node_id), _value_id_key(value_id))
        return self._values.get(key)

    def invoke_cc_api(
        self,
        *,
        node_id: int,
        command_class: int,
        method_name: str,
        args: list | None = None,
        timeout_seconds: float = 10.0,  # noqa: ARG002
    ) -> object:
        key = (node_id, command_class, method_name, json.dumps(args or [], sort_keys=True))
        return self._cc_api_responses.get(key)


def _value_id_key(value_id: dict) -> str:
    # Stable string key for fake gateway maps.
    command_class = value_id.get("commandClass")
    prop = value_id.get("property")
    prop_key = value_id.get("propertyKey")
    return f"{command_class}:{prop}:{prop_key}"


class LockConfigSyncApiTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.client.force_authenticate(self.admin)

        profile = ensure_active_settings_profile()

        # Enable ZWaveJS in DB (replaces env var patches)
        definition = ALARM_PROFILE_SETTINGS_BY_KEY["zwavejs"]
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=profile,
            key="zwavejs",
            defaults={"value": definition.default, "value_type": definition.value_type},
        )
        entry.set_value_with_encryption({"enabled": True, "ws_url": "ws://example.invalid:3000"})

        Entity.objects.create(
            entity_id="lock.front_door",
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 5}},
            source="home_assistant",
        )

    def test_sync_creates_codes_and_applies_supported_schedule(self):
        value_ids = [
            {"commandClass": 99, "property": "usersNumber"},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1},
            {"commandClass": 99, "property": "userCode", "propertyKey": 1},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 2},
            {"commandClass": 99, "property": "userCode", "propertyKey": 2},
            {"commandClass": 78, "property": "weekDaySchedule", "propertyKey": {"userId": 1, "weekday": 1, "slot": 1}},
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): 2,
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): "1234",
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 2})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 2})): "****",
            (
                5,
                _value_id_key(
                    {
                        "commandClass": 78,
                        "property": "weekDaySchedule",
                        "propertyKey": {"userId": 1, "weekday": 1, "slot": 1},
                    }
                ),
            ): {
                "startHour": 8,
                "startMinute": 0,
                "durationHour": 8,
                "durationMinute": 0,
            },
        }
        fake = FakeZwavejsGateway(value_ids=value_ids, values=values)

        url = reverse("locks-sync-config", kwargs={"lock_entity_id": "lock.front_door"})
        with patch("locks.views.lock_config_sync.zwavejs_gateway", fake):
            response = self.client.post(
                url,
                {"user_id": str(self.user.id), "reauth_password": "pass"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()["data"]
        self.assertEqual(body["created"], 2)
        self.assertEqual(body["errors"], 0)

        slot1 = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door", slot_index=1
        )
        self.assertEqual(slot1.door_code.user_id, self.user.id)
        self.assertEqual(slot1.door_code.source, DoorCode.Source.SYNCED)
        self.assertEqual(slot1.door_code.code_type, DoorCode.CodeType.TEMPORARY)
        self.assertEqual(slot1.door_code.days_of_week, 1)  # Monday only
        self.assertEqual(str(slot1.door_code.window_start), "08:00:00")
        self.assertEqual(str(slot1.door_code.window_end), "16:00:00")
        self.assertIsNotNone(slot1.door_code.encrypted_pin)
        self.assertEqual(slot1.door_code.pin_length, 4)

        slot2 = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door", slot_index=2
        )
        self.assertIsNone(slot2.door_code.encrypted_pin)
        self.assertIsNone(slot2.door_code.pin_length)

    def test_sync_returns_conflict_when_already_in_progress(self):
        url = reverse("locks-sync-config", kwargs={"lock_entity_id": "lock.front_door"})
        fake = FakeZwavejsGateway(value_ids=[], values={})
        with (
            patch("locks.views.lock_config_sync.zwavejs_gateway", fake),
            patch("locks.use_cases.lock_config_sync._try_acquire_sync_lock", return_value=(False, None)),
        ):
            response = self.client.post(url, {"user_id": str(self.user.id), "reauth_password": "pass"}, format="json")
        self.assertEqual(response.status_code, 409)

    # --- Helper to run a sync with a given fake gateway ---

    def _sync(self, fake):
        url = reverse("locks-sync-config", kwargs={"lock_entity_id": "lock.front_door"})
        with patch("locks.views.lock_config_sync.zwavejs_gateway", fake):
            return self.client.post(
                url,
                {"user_id": str(self.user.id), "reauth_password": "pass"},
                format="json",
            )

    def _make_single_slot_gateway(self, *, slot_status=1, pin="1234"):
        """Create a gateway with a single slot (slot 1)."""
        value_ids = [
            {"commandClass": 99, "property": "usersNumber"},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1},
            {"commandClass": 99, "property": "userCode", "propertyKey": 1},
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): slot_status,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): pin,
        }
        return FakeZwavejsGateway(value_ids=value_ids, values=values)

    # --- Re-sync: idempotent (slot unchanged) ---

    def test_resync_slot_unchanged_is_idempotent(self):
        # Use a masked PIN so encrypted_pin stays None across syncs.
        fake = self._make_single_slot_gateway(pin="****")

        # First sync — creates the code with encrypted_pin=None.
        resp1 = self._sync(fake)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["data"]["created"], 1)

        original = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door",
            slot_index=1,
        )
        self.assertIsNone(original.door_code.encrypted_pin)

        # Second sync — same masked PIN, should be unchanged.
        resp2 = self._sync(fake)
        self.assertEqual(resp2.status_code, 200)
        body = resp2.json()["data"]
        self.assertEqual(body["unchanged"], 1)
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["updated"], 0)

    # --- Re-sync: PIN changed ---

    def test_resync_slot_pin_changed_updates_code(self):
        fake_v1 = self._make_single_slot_gateway(pin="1234")
        resp1 = self._sync(fake_v1)
        self.assertEqual(resp1.status_code, 200)

        original = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door",
            slot_index=1,
        )
        original_hash = original.door_code.encrypted_pin

        # Re-sync with a different PIN.
        fake_v2 = self._make_single_slot_gateway(pin="5678")
        resp2 = self._sync(fake_v2)
        self.assertEqual(resp2.status_code, 200)
        body = resp2.json()["data"]
        self.assertEqual(body["updated"], 1)
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["unchanged"], 0)

        original.door_code.refresh_from_db()
        self.assertNotEqual(original.door_code.encrypted_pin, original_hash)
        self.assertEqual(original.door_code.pin_length, 4)

    # --- Re-sync: slot emptied (deactivation) ---

    def test_resync_slot_emptied_deactivates_code(self):
        fake_v1 = self._make_single_slot_gateway(pin="1234")
        resp1 = self._sync(fake_v1)
        self.assertEqual(resp1.status_code, 200)

        assignment = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door",
            slot_index=1,
        )
        self.assertTrue(assignment.door_code.is_active)

        # Re-sync: slot is now empty (status 0 = Available).
        fake_v2 = self._make_single_slot_gateway(slot_status=0, pin=None)
        resp2 = self._sync(fake_v2)
        self.assertEqual(resp2.status_code, 200)
        body = resp2.json()["data"]
        self.assertEqual(body["deactivated"], 1)
        self.assertEqual(body["created"], 0)

        assignment.door_code.refresh_from_db()
        self.assertFalse(assignment.door_code.is_active)

    # --- Re-sync: new slot appeared ---

    def test_resync_new_slot_appeared_creates_additional_code(self):
        fake_v1 = self._make_single_slot_gateway(pin="1234")
        resp1 = self._sync(fake_v1)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["data"]["created"], 1)

        # Re-sync: now two slots are occupied.
        value_ids = [
            {"commandClass": 99, "property": "usersNumber"},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1},
            {"commandClass": 99, "property": "userCode", "propertyKey": 1},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 2},
            {"commandClass": 99, "property": "userCode", "propertyKey": 2},
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): 2,
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): "1234",
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 2})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 2})): "9999",
        }
        fake_v2 = FakeZwavejsGateway(value_ids=value_ids, values=values)
        resp2 = self._sync(fake_v2)
        self.assertEqual(resp2.status_code, 200)
        body = resp2.json()["data"]
        self.assertEqual(body["created"], 1)  # only the new slot
        self.assertIn(body["unchanged"] + body["updated"], [1])  # slot 1 either unchanged or updated

        self.assertEqual(
            DoorCodeLockAssignment.objects.filter(lock_entity_id="lock.front_door").count(),
            2,
        )

    # --- Slot 0 (master code) skipped ---

    def test_sync_skips_slot_zero_master_code(self):
        """Slot 0 is the master code — the range starts at 1 so slot 0 is never scanned."""
        value_ids = [
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 0},
            {"commandClass": 99, "property": "userCode", "propertyKey": 0},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1},
            {"commandClass": 99, "property": "userCode", "propertyKey": 1},
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 0})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 0})): "0000",
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): "1234",
        }
        fake = FakeZwavejsGateway(value_ids=value_ids, values=values)
        resp = self._sync(fake)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]

        # Slot 0 is never scanned (range starts at 1); only slot 1 is imported.
        self.assertEqual(body["created"], 1)
        slot_actions = {s["slot_index"]: s["action"] for s in body["slots"]}
        self.assertNotIn(0, slot_actions)
        self.assertEqual(slot_actions.get(1), "created")

        # No assignment for slot 0.
        self.assertFalse(DoorCodeLockAssignment.objects.filter(lock_entity_id="lock.front_door", slot_index=0).exists())

    # --- Node doesn't support CC 0x63 (User Code) ---

    def test_sync_rejects_node_without_user_code_cc(self):
        """A lock without CC 99 value IDs should return a validation error."""
        value_ids = [
            {"commandClass": 98, "property": "doorLock"},
        ]
        fake = FakeZwavejsGateway(value_ids=value_ids, values={})
        resp = self._sync(fake)
        self.assertIn(resp.status_code, [400, 422])

    # --- Mid-sync WebSocket failure ---

    def test_sync_handles_mid_sync_websocket_failure(self):
        """If reading a slot status raises, that slot is reported as an error but others succeed."""

        class FailingGateway(FakeZwavejsGateway):
            def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
                key = (int(node_id), _value_id_key(value_id))
                # Fail on slot 2 status read.
                if value_id.get("property") == "userIdStatus" and value_id.get("propertyKey") == 2:
                    raise ConnectionError("WebSocket closed")
                return self._values.get(key)

        value_ids = [
            {"commandClass": 99, "property": "usersNumber"},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1},
            {"commandClass": 99, "property": "userCode", "propertyKey": 1},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 2},
            {"commandClass": 99, "property": "userCode", "propertyKey": 2},
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): 2,
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): "1234",
        }
        fake = FailingGateway(value_ids=value_ids, values=values)
        resp = self._sync(fake)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        self.assertEqual(body["created"], 1)  # slot 1 succeeds
        self.assertEqual(body["errors"], 1)  # slot 2 fails

        slot_actions = {s["slot_index"]: s for s in body["slots"]}
        self.assertEqual(slot_actions[1]["action"], "created")
        self.assertEqual(slot_actions[2]["action"], "error")
        self.assertIn("ConnectionError", slot_actions[2]["error"])

    # --- Dry-run ---

    def test_dry_run_returns_flag_and_does_not_persist(self):
        """POST with ?dry_run=true returns dry_run=True in response and creates no DB rows."""
        fake = self._make_single_slot_gateway(pin="1234")
        url = reverse("locks-sync-config", kwargs={"lock_entity_id": "lock.front_door"})
        with patch("locks.views.lock_config_sync.zwavejs_gateway", fake):
            response = self.client.post(
                f"{url}?dry_run=true",
                {"user_id": str(self.user.id), "reauth_password": "pass"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()["data"]
        self.assertTrue(body["dry_run"])
        self.assertEqual(body["created"], 1)

        # Nothing persisted.
        self.assertFalse(DoorCodeLockAssignment.objects.filter(lock_entity_id="lock.front_door").exists())
        self.assertFalse(DoorCode.objects.filter(source=DoorCode.Source.SYNCED).exists())

    def test_dry_run_does_not_fire_dispatcher(self):
        """Dry-run must not call notify_entities_changed."""
        fake = self._make_single_slot_gateway(pin="1234")
        url = reverse("locks-sync-config", kwargs={"lock_entity_id": "lock.front_door"})
        with (
            patch("locks.views.lock_config_sync.zwavejs_gateway", fake),
            patch("alarm.dispatcher.notify_entities_changed") as mock_notify,
        ):
            response = self.client.post(
                f"{url}?dry_run=true",
                {"user_id": str(self.user.id), "reauth_password": "pass"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        mock_notify.assert_not_called()

    # --- CC API fallback for daily repeating schedules (ADR 0081) ---

    def test_sync_imports_daily_repeating_schedule_via_cc_api(self):
        """When no CC 78 value IDs exist, fall back to invoke_cc_api for schedules."""
        value_ids = [
            {"commandClass": 99, "property": "usersNumber"},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1},
            {"commandClass": 99, "property": "userCode", "propertyKey": 1},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 2},
            {"commandClass": 99, "property": "userCode", "propertyKey": 2},
            # No CC 78 value IDs — triggers CC API fallback.
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): 2,
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): "1234",
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 2})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 2})): "5678",
        }
        cc_api_responses = {
            # getNumSlots response
            (5, 78, "getNumSlots", "[]"): {"numWeekDaySlots": 0, "numYearDaySlots": 0, "numDailyRepeatingSlots": 7},
            # User 1, slot 1: empty schedule
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 1, "userId": 1}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 2, "userId": 1}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 3, "userId": 1}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 4, "userId": 1}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 5, "userId": 1}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 6, "userId": 1}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 7, "userId": 1}]'): {},
            # User 2, slot 1: Mon+Thu 07:00 for 8h
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 1, "userId": 2}]'): {
                "weekdays": [1, 4],
                "startHour": 7,
                "startMinute": 0,
                "durationHour": 8,
                "durationMinute": 0,
            },
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 2, "userId": 2}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 3, "userId": 2}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 4, "userId": 2}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 5, "userId": 2}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 6, "userId": 2}]'): {},
            (5, 78, "getDailyRepeatingSchedule", '[{"slotId": 7, "userId": 2}]'): {},
        }
        fake = FakeZwavejsGateway(value_ids=value_ids, values=values, cc_api_responses=cc_api_responses)
        resp = self._sync(fake)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        self.assertEqual(body["created"], 2)
        self.assertEqual(body["errors"], 0)

        # Slot 1: no schedule
        slot1 = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door", slot_index=1
        )
        self.assertIsNone(slot1.door_code.days_of_week)

        # Slot 2: Mon (bit 0) + Thu (bit 3) = 0b1001 = 9
        slot2 = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door", slot_index=2
        )
        self.assertEqual(slot2.door_code.days_of_week, 9)
        self.assertEqual(str(slot2.door_code.window_start), "07:00:00")
        self.assertEqual(str(slot2.door_code.window_end), "15:00:00")
        self.assertEqual(slot2.door_code.code_type, DoorCode.CodeType.TEMPORARY)

    def test_sync_cc_api_graceful_when_no_daily_slots(self):
        """If the lock reports 0 daily repeating slots, schedules are unsupported but sync completes."""
        value_ids = [
            {"commandClass": 99, "property": "usersNumber"},
            {"commandClass": 99, "property": "userIdStatus", "propertyKey": 1},
            {"commandClass": 99, "property": "userCode", "propertyKey": 1},
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): "1234",
        }
        cc_api_responses = {
            (5, 78, "getNumSlots", "[]"): {"numWeekDaySlots": 0, "numYearDaySlots": 0, "numDailyRepeatingSlots": 0},
        }
        fake = FakeZwavejsGateway(value_ids=value_ids, values=values, cc_api_responses=cc_api_responses)
        resp = self._sync(fake)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()["data"]
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["errors"], 0)


class SlotGateway(FakeZwavejsGateway):
    """A lock whose slots are given as ``{slot: (userIdStatus, userCode)}``.

    ``failing_status_slots`` raise on the status read and CC 99 clears are recorded.
    """

    def __init__(self, slots: dict[int, tuple[object, object]], *, failing_status_slots: set[int] = frozenset()):
        value_ids = [{"commandClass": 99, "property": "usersNumber"}]
        values: dict[tuple[int, str], object] = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): max(slots),
        }
        for slot, (status, pin) in slots.items():
            for prop, value in (("userIdStatus", status), ("userCode", pin)):
                value_id = {"commandClass": 99, "property": prop, "propertyKey": slot}
                value_ids.append(value_id)
                values[(5, _value_id_key(value_id))] = value
        super().__init__(value_ids=value_ids, values=values)
        self.failing_status_slots = set(failing_status_slots)
        self.clears: list[int] = []

    def node_get_value(self, *, node_id, value_id, timeout_seconds=5.0):
        if value_id.get("property") == "userIdStatus" and value_id.get("propertyKey") in self.failing_status_slots:
            raise TimeoutError("lock asleep")
        return super().node_get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)

    def invoke_cc_api(self, *, node_id, command_class, method_name, args=None, timeout_seconds=10.0):
        if command_class == 99 and method_name == "clear":
            self.clears.append(int((args or [None])[0]))
            return None
        return super().invoke_cc_api(
            node_id=node_id,
            command_class=command_class,
            method_name=method_name,
            args=args,
            timeout_seconds=timeout_seconds,
        )


class LockConfigSyncReconcileTests(EncryptionTestMixin, APITestCase):
    """Issues #149, #150 and #140: what a sync may change on codes latchpoint already tracks."""

    LOCK = "lock.front_door"

    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.client.force_authenticate(self.admin)
        profile = ensure_active_settings_profile()
        definition = ALARM_PROFILE_SETTINGS_BY_KEY["zwavejs"]
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=profile,
            key="zwavejs",
            defaults={"value": definition.default, "value_type": definition.value_type},
        )
        entry.set_value_with_encryption({"enabled": True, "ws_url": "ws://example.invalid:3000"})
        Entity.objects.create(
            entity_id=self.LOCK,
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 5}},
            source="home_assistant",
        )

    def _sync(self, fake):
        url = reverse("locks-sync-config", kwargs={"lock_entity_id": self.LOCK})
        with patch("locks.views.lock_config_sync.zwavejs_gateway", fake):
            response = self.client.post(url, {"user_id": str(self.user.id), "reauth_password": "pass"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["data"]

    def _manual_code(self, *, pin: str, slot_index: int | None, is_active: bool = True) -> DoorCode:
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.MANUAL,
            encrypted_pin=SettingsEncryption.get().encrypt(pin),
            pin_length=len(pin),
            label="Dog walker",
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=is_active,
            push_state=DoorCode.PushState.PUSHED,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK, slot_index=slot_index)
        return code

    @staticmethod
    def _slot(body, slot_index):
        return next(s for s in body["slots"] if s["slot_index"] == slot_index)

    # --- #149: turning synced codes off ---

    def test_failed_slot_read_does_not_turn_off_synced_code(self):
        self._sync(SlotGateway({1: (1, "1234"), 2: (1, "5678")}))
        assignment = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id=self.LOCK, slot_index=2
        )

        body = self._sync(SlotGateway({1: (1, "1234"), 2: (1, "5678")}, failing_status_slots={2}))

        self.assertEqual(body["deactivated"], 0)
        self.assertEqual(self._slot(body, 2)["action"], "error")
        assignment.refresh_from_db()
        assignment.door_code.refresh_from_db()
        self.assertTrue(assignment.door_code.is_active)
        self.assertEqual(assignment.slot_index, 2)

    def test_inconclusive_slot_status_does_not_turn_off_synced_code(self):
        self._sync(SlotGateway({1: (1, "1234")}))
        assignment = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id=self.LOCK, slot_index=1
        )

        # 254 = status not available; None = nothing in the value cache.
        for status in (254, None):
            body = self._sync(SlotGateway({1: (status, None)}))
            self.assertEqual(body["deactivated"], 0)
            assignment.refresh_from_db()
            assignment.door_code.refresh_from_db()
            self.assertTrue(assignment.door_code.is_active)
            self.assertEqual(assignment.slot_index, 1)

    def test_confirmed_empty_slot_turns_code_off_and_releases_slot(self):
        self._sync(SlotGateway({1: (1, "1234")}))
        assignment = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id=self.LOCK, slot_index=1
        )

        body = self._sync(SlotGateway({1: (0, None)}))

        self.assertEqual(body["deactivated"], 1)
        assignment.refresh_from_db()
        assignment.door_code.refresh_from_db()
        self.assertFalse(assignment.door_code.is_active)
        self.assertIsNone(assignment.slot_index)
        self.assertTrue(
            DoorCodeEvent.objects.filter(
                door_code=assignment.door_code, metadata__action="deactivated", metadata__slot_index=1
            ).exists()
        )

    def test_confirmed_empty_slot_releases_slot_of_already_inactive_synced_code(self):
        # A synced code an older sync turned off but left on "slot 1".
        self._sync(SlotGateway({1: (1, "1234")}))
        assignment = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id=self.LOCK, slot_index=1
        )
        DoorCode.objects.filter(id=assignment.door_code_id).update(is_active=False)

        body = self._sync(SlotGateway({1: (0, None)}))

        self.assertEqual(body["deactivated"], 0)
        assignment.refresh_from_db()
        self.assertIsNone(assignment.slot_index)

    def test_sync_creates_codes_as_pushed(self):
        self._sync(SlotGateway({1: (1, "1234"), 2: (2, "****")}))

        codes = DoorCode.objects.filter(source=DoorCode.Source.SYNCED)
        self.assertEqual(codes.count(), 2)
        self.assertEqual(set(codes.values_list("push_state", flat=True)), {DoorCode.PushState.PUSHED})

    # --- #150: manual -> synced conversion ---

    def test_conversion_skipped_when_clear_failure_outstanding(self):
        # #144 turned the code off after a delete whose clear of slot 1 failed.
        code = self._manual_code(pin="1234", slot_index=1, is_active=False)
        lock_push_uc.record_clear_failure(
            door_code=code, lock_entity_id=self.LOCK, slot_index=1, exc=TimeoutError("asleep"), expected_pin="1234"
        )

        body = self._sync(SlotGateway({1: (1, "1234")}))

        self.assertEqual(body["skipped"], 1)
        self.assertEqual(body["updated"], 0)
        slot = self._slot(body, 1)
        self.assertEqual(slot["action"], "skipped")
        self.assertEqual(slot["door_code_id"], code.id)
        self.assertIn("clear_outstanding", slot["warnings"])
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.MANUAL)
        self.assertFalse(code.is_active)
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), "1234")
        self.assertTrue(
            DoorCodeEvent.objects.filter(
                door_code=code, metadata__action="sync_skipped", metadata__reason="clear_outstanding"
            ).exists()
        )
        # Nothing that would close the code's push_unconfirmed window or settle the clear.
        self.assertFalse(
            DoorCodeEvent.objects.filter(door_code=code, event_type=DoorCodeEvent.EventType.CODE_SYNCED).exists()
        )
        self.assertEqual(len(lock_push_uc.unresolved_clear_failures(door_code=code)), 1)

    def test_conversion_skipped_for_inactive_manual_code(self):
        code = self._manual_code(pin="1234", slot_index=1, is_active=False)

        body = self._sync(SlotGateway({1: (1, "1234")}))

        self.assertIn("inactive_code_on_lock", self._slot(body, 1)["warnings"])
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.MANUAL)
        self.assertFalse(code.is_active)

    def test_stale_pin_mismatch_flagged_not_adopted(self):
        # The code's PIN is now 5555 but slot 1 still holds the old 1234.
        code = self._manual_code(pin="5555", slot_index=1)

        body = self._sync(SlotGateway({1: (1, "1234")}))

        self.assertEqual(body["skipped"], 1)
        slot = self._slot(body, 1)
        self.assertEqual(slot["action"], "skipped")
        self.assertIn("pin_mismatch", slot["warnings"])
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.MANUAL)
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), "5555")
        self.assertTrue(
            DoorCodeEvent.objects.filter(
                door_code=code, metadata__action="sync_skipped", metadata__reason="pin_mismatch"
            ).exists()
        )

    def test_conversion_with_matching_or_masked_pin_keeps_code_pin(self):
        matching = self._manual_code(pin="1234", slot_index=1)
        masked = self._manual_code(pin="5678", slot_index=2)

        self._sync(SlotGateway({1: (1, "1234"), 2: (1, "****")}))

        for code, pin in ((matching, "1234"), (masked, "5678")):
            code.refresh_from_db()
            self.assertEqual(code.source, DoorCode.Source.SYNCED)
            self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), pin)
            self.assertEqual(code.pin_length, 4)

    def test_untracked_slot_with_unconfirmed_push_is_not_imported(self):
        # A push wrote 4321 to slot 2 but never got it confirmed (#111).
        code = self._manual_code(pin="4321", slot_index=None)
        code.push_state = DoorCode.PushState.PENDING
        code.save(update_fields=["push_state"])
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=self.LOCK, slot_index=2, reason="readback timed out", pin="4321"
        )

        body = self._sync(SlotGateway({1: (0, None), 2: (1, "4321")}))

        self.assertEqual(body["created"], 0)
        slot = self._slot(body, 2)
        self.assertEqual(slot["action"], "skipped")
        self.assertEqual(slot["door_code_id"], code.id)
        self.assertIn("clear_outstanding", slot["warnings"])
        self.assertFalse(DoorCodeLockAssignment.objects.filter(lock_entity_id=self.LOCK, slot_index=2).exists())
        # The unconfirmed window stays open for the code's own cleanup.
        self.assertEqual(lock_push_uc._unconfirmed_attempt_slots(door_code=code, lock_entity_id=self.LOCK), [2])

    # --- #140: copies of a PIN stranded by #133 ---

    def test_stranded_copy_is_imported_as_flagged_synced_code_and_delete_clears_it(self):
        # #133 left back with {1: PIN, 2: PIN} with only slot 2 tracked.
        code = self._manual_code(pin="4321", slot_index=2)
        fake = SlotGateway({1: (1, "4321"), 2: (1, "4321")})

        body = self._sync(fake)

        stranded = self._slot(body, 1)
        self.assertEqual(stranded["action"], "created")
        self.assertIn("duplicate_pin", stranded["warnings"])
        self.assertEqual(stranded["duplicate_pin_door_code_ids"], [code.id])
        self.assertEqual(self._slot(body, 2)["duplicate_pin_door_code_ids"], [])
        copy = DoorCode.objects.get(id=stranded["door_code_id"])
        self.assertEqual(copy.source, DoorCode.Source.SYNCED)
        self.assertTrue(
            DoorCodeEvent.objects.filter(
                door_code=copy, metadata__action="created", metadata__duplicate_pin_door_code_ids=[code.id]
            ).exists()
        )

        # The cleanup path: delete the imported copy, which clears only its slot.
        door_codes_uc.delete_door_code(code=copy, actor_user=self.admin, zwavejs=fake)
        self.assertEqual(fake.clears, [1])
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 2)

    def test_untracked_slot_holding_pin_of_code_without_slot_is_flagged(self):
        # The Yale case: the push went `failed` on this lock but slot 1 kept the PIN.
        code = self._manual_code(pin="4321", slot_index=None)
        DoorCode.objects.filter(id=code.id).update(push_state=DoorCode.PushState.FAILED)

        fake = SlotGateway({1: (1, "4321")})

        body = self._sync(fake)

        self.assertEqual(self._slot(body, 1)["duplicate_pin_door_code_ids"], [code.id])
        self.assertEqual(fake.clears, [])  # the sync only flags, it never clears

    # --- #165 review follow-ups ---

    def _synced_code_at(self, slot_index: int, pin: str) -> DoorCode:
        self._sync(SlotGateway({slot_index: (1, pin)}))
        return DoorCodeLockAssignment.objects.get(lock_entity_id=self.LOCK, slot_index=slot_index).door_code

    def _clear_failed(self, code: DoorCode, slot_index: int, expected_pin: str) -> None:
        lock_push_uc.record_clear_failure(
            door_code=code,
            lock_entity_id=self.LOCK,
            slot_index=slot_index,
            exc=TimeoutError("asleep"),
            expected_pin=expected_pin,
        )

    def _unconfirmed(self, code: DoorCode, slot_index: int, pin: str) -> None:
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id=self.LOCK, slot_index=slot_index, reason="readback timed out", pin=pin
        )

    def test_untracked_slot_with_clear_failure_is_not_imported_while_it_holds_the_expected_pin(self):
        # A dropped lock whose clear of slot 3 keeps failing (at the attempt cap, say).
        for slot_value in ("4321", "****"):
            with self.subTest(slot_value=slot_value):
                code = self._manual_code(pin="4321", slot_index=None)
                self._clear_failed(code, 3, "4321")

                body = self._sync(SlotGateway({3: (1, slot_value)}))

                slot = self._slot(body, 3)
                self.assertEqual(slot["action"], "skipped")
                self.assertEqual(slot["door_code_id"], code.id)
                self.assertIn("clear_outstanding", slot["warnings"])
                self.assertFalse(DoorCodeLockAssignment.objects.filter(lock_entity_id=self.LOCK, slot_index=3).exists())
                code.delete()

    def test_untracked_slot_holding_another_pin_than_the_marker_expects_is_imported(self):
        # Someone programmed 9999 on the keypad into a slot latchpoint still has a marker for.
        cleared = self._manual_code(pin="4321", slot_index=None)
        self._clear_failed(cleared, 3, "4321")
        unconfirmed = self._manual_code(pin="5678", slot_index=None)
        self._unconfirmed(unconfirmed, 4, "5678")

        body = self._sync(SlotGateway({3: (1, "9999"), 4: (1, "8888")}))

        self.assertEqual(body["created"], 2)
        self.assertEqual(self._slot(body, 3)["action"], "created")
        self.assertEqual(self._slot(body, 4)["action"], "created")
        imported = DoorCodeLockAssignment.objects.get(lock_entity_id=self.LOCK, slot_index=3).door_code
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(imported), "9999")

    def test_masked_read_keeps_synced_code_pin(self):
        code = self._manual_code(pin="1234", slot_index=1)
        self._sync(SlotGateway({1: (1, "1234")}))  # converts it
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.SYNCED)

        for unreadable in ("****", None):
            self._sync(SlotGateway({1: (1, unreadable)}))
            code.refresh_from_db()
            self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), "1234")
            self.assertEqual(code.pin_length, 4)

        # A readable PIN that differs still wins for a synced code.
        self._sync(SlotGateway({1: (1, "987654")}))
        code.refresh_from_db()
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), "987654")
        self.assertEqual(code.pin_length, 6)

    def test_slot_release_skipped_while_unconfirmed_push_outstanding(self):
        code = self._synced_code_at(1, "1234")
        self._unconfirmed(code, 3, "1234")

        body = self._sync(SlotGateway({1: (0, None), 3: (0, None)}))

        self.assertEqual(body["deactivated"], 0)
        slot = self._slot(body, 1)
        self.assertEqual(slot["action"], "skipped")
        self.assertIn("clear_outstanding", slot["warnings"])
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 1)
        # The window is still open, so #111's cleanup still checks slot 3.
        self.assertEqual(lock_push_uc._unconfirmed_attempt_slots(door_code=code, lock_entity_id=self.LOCK), [3])

    def test_existing_code_with_only_an_unconfirmed_push_is_skipped(self):
        code = self._manual_code(pin="1234", slot_index=1)
        self._unconfirmed(code, 3, "1234")

        body = self._sync(SlotGateway({1: (1, "1234"), 3: (0, None)}))

        self.assertIn("clear_outstanding", self._slot(body, 1)["warnings"])
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.MANUAL)

    def test_synced_code_with_clear_failure_is_skipped(self):
        code = self._synced_code_at(1, "1234")
        self._clear_failed(code, 1, "1234")

        body = self._sync(SlotGateway({1: (1, "9999")}))

        self.assertIn("clear_outstanding", self._slot(body, 1)["warnings"])
        code.refresh_from_db()
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(code), "1234")

    def test_release_only_touches_synced_codes(self):
        code = self._manual_code(pin="1234", slot_index=1)

        body = self._sync(SlotGateway({1: (0, None)}))

        self.assertEqual(body["deactivated"], 0)
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 1)

    def test_status_text_other_than_available_does_not_release_slot(self):
        code = self._synced_code_at(1, "1234")

        self._sync(SlotGateway({1: ("Status not available", None)}))
        self.assertEqual(DoorCodeLockAssignment.objects.get(door_code=code).slot_index, 1)

        self._sync(SlotGateway({1: ("Available", None)}))
        self.assertIsNone(DoorCodeLockAssignment.objects.get(door_code=code).slot_index)

    def test_codes_sharing_a_pin_in_their_own_slots_are_not_flagged(self):
        self._manual_code(pin="1111", slot_index=1)
        self._manual_code(pin="1111", slot_index=2)

        body = self._sync(SlotGateway({1: (1, "1111"), 2: (1, "1111")}))

        for slot_index in (1, 2):
            self.assertNotIn("duplicate_pin", self._slot(body, slot_index)["warnings"])
            self.assertEqual(self._slot(body, slot_index)["duplicate_pin_door_code_ids"], [])

    def test_duplicate_pin_compares_against_pins_after_the_sync(self):
        # Slot 1's synced code was 4321 but the lock now has 5555 there, and 4321 is in slot 2.
        self._synced_code_at(1, "4321")

        body = self._sync(SlotGateway({1: (1, "5555"), 2: (1, "4321")}))

        self.assertEqual(self._slot(body, 2)["action"], "created")
        self.assertNotIn("duplicate_pin", self._slot(body, 2)["warnings"])

    # --- after #167: only unsettled attempts a cleanup would act on count ---

    def _settle(self, code: DoorCode, slot_index: int, lock_entity_id: str | None = None) -> None:
        lock_push_uc._settle_unconfirmed_slot(
            door_code=code, lock_entity_id=lock_entity_id or self.LOCK, slot_index=slot_index, outcome="cleared"
        )

    def test_settled_unconfirmed_attempt_does_not_block_conversion(self):
        code = self._manual_code(pin="1234", slot_index=1)
        self._unconfirmed(code, 3, "1234")
        self._settle(code, 3)

        body = self._sync(SlotGateway({1: (1, "1234"), 3: (0, None)}))

        self.assertNotIn("clear_outstanding", self._slot(body, 1)["warnings"])
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.SYNCED)

    def test_settled_unconfirmed_attempt_does_not_block_import(self):
        code = self._manual_code(pin="4321", slot_index=None)
        self._unconfirmed(code, 2, "4321")
        self._settle(code, 2)

        body = self._sync(SlotGateway({2: (1, "4321")}))

        self.assertEqual(self._slot(body, 2)["action"], "created")

    def test_unsettled_attempt_on_a_dropped_lock_blocks_conversion(self):
        code = self._manual_code(pin="1234", slot_index=1)
        lock_push_uc._record_unconfirmed_slot_attempt(
            door_code=code, lock_entity_id="lock.back_door", slot_index=2, reason="readback timed out", pin="1234"
        )

        body = self._sync(SlotGateway({1: (1, "1234")}))

        self.assertIn("clear_outstanding", self._slot(body, 1)["warnings"])
        code.refresh_from_db()
        self.assertEqual(code.source, DoorCode.Source.MANUAL)

    def test_attempt_with_no_pin_to_compare_does_not_block_import(self):
        # The cleanup skips an attempt it has no PIN for, so it would never settle.
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.MANUAL,
            code_type=DoorCode.CodeType.PERMANENT,
            push_state=DoorCode.PushState.PENDING,
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id=self.LOCK, slot_index=None)
        DoorCodeEvent.objects.create(
            door_code=code,
            lock_entity_id=self.LOCK,
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={"action": "push_unconfirmed", "slot_index": 2, "reason": "readback timed out"},
        )

        body = self._sync(SlotGateway({2: (1, "4321")}))

        self.assertEqual(self._slot(body, 2)["action"], "created")

    def test_integrity_race_fallback_keeps_the_150_guards(self):
        # Another writer puts this manual code (PIN 5555) on slot 1 between the lookup and the insert.
        winner = self._manual_code(pin="5555", slot_index=None)

        def take_slot_first(sender, instance, created, **kwargs):
            # Runs right after the sync saves its new code and before it inserts the assignment.
            if created and instance.source == DoorCode.Source.SYNCED:
                DoorCodeLockAssignment.objects.filter(door_code=winner).update(slot_index=1)

        post_save.connect(take_slot_first, sender=DoorCode)
        try:
            body = self._sync(SlotGateway({1: (1, "1234")}))
        finally:
            post_save.disconnect(take_slot_first, sender=DoorCode)

        slot = self._slot(body, 1)
        self.assertEqual(slot["action"], "skipped")
        self.assertEqual(slot["door_code_id"], winner.id)
        self.assertIn("integrity_race", slot["warnings"])
        self.assertIn("pin_mismatch", slot["warnings"])
        winner.refresh_from_db()
        self.assertEqual(lock_push_uc.decrypt_pin_or_none(winner), "5555")
        self.assertEqual(DoorCode.objects.filter(source=DoorCode.Source.SYNCED).count(), 0)


class ConfirmedEmptyStatusTests(TestCase):
    """Only an Available userIdStatus releases a slot (issue #149)."""

    def test_available_values(self):
        for value in (0, "0", 0.0, "Available", " available "):
            with self.subTest(value=value):
                self.assertTrue(_is_confirmed_empty_status(value))

    def test_not_a_verdict(self):
        for value in (1, 2, 254, None, "", "Status not available", "Occupied", "unavailable", True):
            with self.subTest(value=value):
                self.assertFalse(_is_confirmed_empty_status(value))


class BackfillSyncedPushStateTests(DjangoTestCase):
    """Migration 0008 (issue #149)."""

    def _run(self):
        from django.apps import apps

        migration = importlib.import_module("locks.migrations.0008_backfill_synced_code_push_state")
        migration._backfill_synced_push_state(apps, None)

    def _code(self, *, source, push_state, slot_index, user, is_active=True):
        code = DoorCode.objects.create(
            user=user,
            source=source,
            code_type=DoorCode.CodeType.PERMANENT,
            is_active=is_active,
            push_state=push_state,
            last_push_error="Lock busy" if push_state == DoorCode.PushState.PENDING else "",
        )
        DoorCodeLockAssignment.objects.create(door_code=code, lock_entity_id="lock.front_door", slot_index=slot_index)
        return code

    def test_backfill_marks_only_synced_pending_codes_holding_a_slot(self):
        user = User.objects.create_user(email="u@example.com", password="pass")
        synced_on_lock = self._code(source="synced", push_state="pending", slot_index=1, user=user)
        synced_no_slot = self._code(source="synced", push_state="pending", slot_index=None, user=user)
        synced_failed = self._code(source="synced", push_state="failed", slot_index=2, user=user)
        manual_pending = self._code(source="manual", push_state="pending", slot_index=3, user=user)
        synced_clear_failed = self._code(source="synced", push_state="pending", slot_index=4, user=user)
        DoorCodeEvent.objects.create(
            door_code=synced_clear_failed,
            lock_entity_id="lock.front_door",
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={"action": "clear_failed", "slot_index": 4},
        )
        synced_unconfirmed = self._code(source="synced", push_state="pending", slot_index=5, user=user)
        DoorCodeEvent.objects.create(
            door_code=synced_unconfirmed,
            lock_entity_id="lock.front_door",
            event_type=DoorCodeEvent.EventType.CODE_FAILED,
            metadata={"action": "push_unconfirmed", "slot_index": 6},
        )
        synced_inactive = self._code(source="synced", push_state="pending", slot_index=7, user=user, is_active=False)

        self._run()

        def state(code):
            code.refresh_from_db()
            return code.push_state

        self.assertEqual(state(synced_on_lock), "pushed")
        self.assertEqual(synced_on_lock.last_push_error, "")
        self.assertEqual(state(synced_no_slot), "pending")
        self.assertEqual(state(synced_failed), "failed")
        self.assertEqual(state(manual_pending), "pending")
        self.assertEqual(state(synced_clear_failed), "pending")
        self.assertEqual(state(synced_unconfirmed), "pending")
        self.assertEqual(state(synced_inactive), "pending")


class PinNormalizationTests(TestCase):
    """Test _normalize_pin() with various input types (ADR 0068 test checklist)."""

    def test_string_numeric_pin(self):
        known, pin = _normalize_pin("1234")
        self.assertTrue(known)
        self.assertEqual(pin, "1234")

    def test_string_8_digit_pin(self):
        known, pin = _normalize_pin("12345678")
        self.assertTrue(known)
        self.assertEqual(pin, "12345678")

    def test_integer_pin(self):
        known, pin = _normalize_pin(1234)
        self.assertTrue(known)
        self.assertEqual(pin, "1234")

    def test_bytes_pin(self):
        known, pin = _normalize_pin(b"5678")
        self.assertTrue(known)
        self.assertEqual(pin, "5678")

    def test_masked_stars(self):
        known, pin = _normalize_pin("****")
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_masked_bullets(self):
        known, pin = _normalize_pin("\u2022\u2022\u2022\u2022")
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_masked_x(self):
        known, pin = _normalize_pin("xxxx")
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_none_input(self):
        known, pin = _normalize_pin(None)
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_empty_string(self):
        known, pin = _normalize_pin("")
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_too_short(self):
        known, pin = _normalize_pin("123")
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_too_long(self):
        known, pin = _normalize_pin("123456789")
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_non_numeric(self):
        known, pin = _normalize_pin("abcd")
        self.assertFalse(known)
        self.assertIsNone(pin)

    def test_float_integer_pin(self):
        known, pin = _normalize_pin(1234.0)
        self.assertTrue(known)
        self.assertEqual(pin, "1234")
