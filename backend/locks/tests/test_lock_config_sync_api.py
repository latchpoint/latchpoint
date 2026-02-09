from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsEntry, Entity
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.use_cases.lock_config_sync import _normalize_pin


class FakeZwavejsGateway:
    def __init__(self, *, value_ids: list[dict], values: dict[tuple[int, str], object]):
        self._value_ids = value_ids
        self._values = values

    def apply_settings(self, *, settings_obj):  # noqa: ARG002
        return None

    def ensure_connected(self, *, timeout_seconds: float = 5.0):  # noqa: ARG002
        return None

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0):  # noqa: ARG002
        return list(self._value_ids)

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0):  # noqa: ARG002
        key = (int(node_id), _value_id_key(value_id))
        return self._values.get(key)


def _value_id_key(value_id: dict) -> str:
    # Stable string key for fake gateway maps.
    command_class = value_id.get("commandClass")
    prop = value_id.get("property")
    prop_key = value_id.get("propertyKey")
    return f"{command_class}:{prop}:{prop_key}"


class LockConfigSyncApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.client.force_authenticate(self.admin)

        profile = ensure_active_settings_profile()
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="zwavejs_connection",
            defaults={
                "value_type": "json",
                "value": {
                    "enabled": True,
                    "ws_url": "ws://example.invalid:3000",
                    "api_token": "",
                    "connect_timeout_seconds": 1,
                    "reconnect_min_seconds": 1,
                    "reconnect_max_seconds": 1,
                },
            },
        )

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
            {"commandClass": 76, "property": "weekDaySchedule", "propertyKey": {"userId": 1, "weekday": 1, "slot": 1}},
        ]
        values = {
            (5, _value_id_key({"commandClass": 99, "property": "usersNumber"})): 2,
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 1})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 1})): "1234",
            (5, _value_id_key({"commandClass": 99, "property": "userIdStatus", "propertyKey": 2})): 1,
            (5, _value_id_key({"commandClass": 99, "property": "userCode", "propertyKey": 2})): "****",
            (5, _value_id_key({"commandClass": 76, "property": "weekDaySchedule", "propertyKey": {"userId": 1, "weekday": 1, "slot": 1}})): {
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

        slot1 = DoorCodeLockAssignment.objects.select_related("door_code").get(lock_entity_id="lock.front_door", slot_index=1)
        self.assertEqual(slot1.door_code.user_id, self.user.id)
        self.assertEqual(slot1.door_code.source, DoorCode.Source.SYNCED)
        self.assertEqual(slot1.door_code.code_type, DoorCode.CodeType.TEMPORARY)
        self.assertEqual(slot1.door_code.days_of_week, 1)  # Monday only
        self.assertEqual(str(slot1.door_code.window_start), "08:00:00")
        self.assertEqual(str(slot1.door_code.window_end), "16:00:00")
        self.assertIsNotNone(slot1.door_code.code_hash)
        self.assertEqual(slot1.door_code.pin_length, 4)

        slot2 = DoorCodeLockAssignment.objects.select_related("door_code").get(lock_entity_id="lock.front_door", slot_index=2)
        self.assertIsNone(slot2.door_code.code_hash)
        self.assertIsNone(slot2.door_code.pin_length)

    def test_sync_skips_dismissed_slot(self):
        dismissed = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            code_hash=None,
            label="Slot 1",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=None,
            is_active=False,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=dismissed,
            lock_entity_id="lock.front_door",
            slot_index=1,
            sync_dismissed=True,
        )

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
        self.assertEqual(body["dismissed"], 1)
        self.assertEqual(body["created"], 0)

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
        # Use a masked PIN so code_hash stays None across syncs (make_password
        # produces a different salt each time, so known PINs always differ).
        fake = self._make_single_slot_gateway(pin="****")

        # First sync — creates the code with code_hash=None.
        resp1 = self._sync(fake)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["data"]["created"], 1)

        original = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door", slot_index=1,
        )
        self.assertIsNone(original.door_code.code_hash)

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
            lock_entity_id="lock.front_door", slot_index=1,
        )
        original_hash = original.door_code.code_hash

        # Re-sync with a different PIN.
        fake_v2 = self._make_single_slot_gateway(pin="5678")
        resp2 = self._sync(fake_v2)
        self.assertEqual(resp2.status_code, 200)
        body = resp2.json()["data"]
        self.assertEqual(body["updated"], 1)
        self.assertEqual(body["created"], 0)
        self.assertEqual(body["unchanged"], 0)

        original.door_code.refresh_from_db()
        self.assertNotEqual(original.door_code.code_hash, original_hash)
        self.assertEqual(original.door_code.pin_length, 4)

    # --- Re-sync: slot emptied (deactivation) ---

    def test_resync_slot_emptied_deactivates_code(self):
        fake_v1 = self._make_single_slot_gateway(pin="1234")
        resp1 = self._sync(fake_v1)
        self.assertEqual(resp1.status_code, 200)

        assignment = DoorCodeLockAssignment.objects.select_related("door_code").get(
            lock_entity_id="lock.front_door", slot_index=1,
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
            DoorCodeLockAssignment.objects.filter(lock_entity_id="lock.front_door").count(), 2,
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
        self.assertFalse(
            DoorCodeLockAssignment.objects.filter(lock_entity_id="lock.front_door", slot_index=0).exists()
        )

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
