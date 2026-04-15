from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.models import Entity
from locks.models import DoorCode, DoorCodeEvent, DoorCodeLockAssignment


class DoorCodesApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.client.force_authenticate(self.admin)

    def test_list_door_codes_for_self(self):
        DoorCode.objects.create(
            user=self.admin,
            encrypted_pin="not-used-here",
            label="Admin code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )

        url = reverse("door-codes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json()["data"], list)

    def test_admin_can_create_door_code_for_other_user(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "User door code",
                "code": "1234",
                "code_type": DoorCode.CodeType.PERMANENT,
                "lock_entity_ids": ["lock.front_door"],
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["data"]["user_id"], str(self.user.id))
        self.assertEqual(body["data"]["lock_entity_ids"], ["lock.front_door"])

    def test_cannot_set_active_range_on_permanent_code(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Bad code",
                "code": "1234",
                "code_type": DoorCode.CodeType.PERMANENT,
                "start_at": "2025-01-01T00:00:00Z",
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_can_create_temporary_door_code_with_restrictions(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Sat morning",
                "code": "1234",
                "code_type": DoorCode.CodeType.TEMPORARY,
                "days_of_week": 1 << 5,  # Saturday only
                "window_start": "08:00",
                "window_end": "10:00",
                "lock_entity_ids": ["lock.front_door"],
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["data"]["code_type"], DoorCode.CodeType.TEMPORARY)
        self.assertEqual(body["data"]["days_of_week"], 1 << 5)
        self.assertEqual(body["data"]["window_start"], "08:00:00")
        self.assertEqual(body["data"]["window_end"], "10:00:00")

    def test_admin_can_create_one_time_code(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Guest code",
                "code": "5678",
                "code_type": DoorCode.CodeType.ONE_TIME,
                "lock_entity_ids": ["lock.front_door"],
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["code_type"], DoorCode.CodeType.ONE_TIME)

    def test_one_time_code_cannot_have_max_uses(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Bad code",
                "code": "5678",
                "code_type": DoorCode.CodeType.ONE_TIME,
                "max_uses": 5,
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_can_list_door_codes_for_other_user(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="User code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=code,
            lock_entity_id="lock.front_door",
        )

        url = reverse("door-codes")
        response = self.client.get(url, {"user_id": str(self.user.id)})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["user_id"], str(self.user.id))
        self.assertEqual(body["data"][0]["lock_entity_ids"], ["lock.front_door"])

    def test_non_admin_can_read_own_door_code_detail(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="User code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        url = reverse("door-code-detail", args=[code.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["user_id"], str(self.user.id))

    def test_non_admin_cannot_read_other_user_door_code_detail(self):
        other_code = DoorCode.objects.create(
            user=self.admin,
            encrypted_pin="not-used-here",
            label="Admin code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        url = reverse("door-code-detail", args=[other_code.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_create_door_code(self):
        self.client.force_authenticate(self.user)
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "User code",
                "code": "1234",
                "code_type": DoorCode.CodeType.PERMANENT,
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_update_door_code(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="User code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        url = reverse("door-code-detail", args=[code.id])
        response = self.client.patch(
            url,
            {"label": "New", "reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_update_door_code(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="User code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        url = reverse("door-code-detail", args=[code.id])
        response = self.client.patch(
            url,
            {"label": "Updated label", "reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["label"], "Updated label")

    def test_admin_can_update_door_code_lock_assignments(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="User code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        url = reverse("door-code-detail", args=[code.id])
        response = self.client.patch(
            url,
            {"lock_entity_ids": ["lock.front_door"], "reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["lock_entity_ids"], ["lock.front_door"])

    def test_admin_can_delete_door_code(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="User code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        url = reverse("door-code-detail", args=[code.id])
        response = self.client.delete(
            url,
            {"reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(DoorCode.objects.filter(id=code.id).exists())

    def test_deleting_synced_door_code_clears_lock_and_deletes(self):
        Entity.objects.create(
            entity_id="lock.front_door",
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 5}},
            source="zwavejs",
        )
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=None,
            label="Slot 1",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=None,
            is_active=True,
        )
        code_id = code.id
        DoorCodeLockAssignment.objects.create(
            door_code=code,
            lock_entity_id="lock.front_door",
            slot_index=1,
        )

        fake_gw = MagicMock()
        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", fake_gw):
            response = self.client.delete(url, {"reauth_password": "pass"}, format="json")
        self.assertEqual(response.status_code, 204)

        # Verify CC 99 clear was called with correct args.
        fake_gw.invoke_cc_api.assert_called_once_with(
            node_id=5,
            command_class=99,
            method_name="clear",
            args=[1],
            timeout_seconds=10.0,
        )

        # Code and assignment should be fully deleted from DB.
        self.assertFalse(DoorCode.objects.filter(id=code_id).exists())
        self.assertFalse(DoorCodeLockAssignment.objects.filter(lock_entity_id="lock.front_door", slot_index=1).exists())

        # Verify audit event records cleared_from_lock=True.
        event = DoorCodeEvent.objects.filter(event_type=DoorCodeEvent.EventType.CODE_DELETED).first()
        self.assertIsNotNone(event)
        self.assertTrue(event.metadata.get("cleared_from_lock"))

        list_url = reverse("door-codes")
        list_resp = self.client.get(list_url, {"user_id": str(self.user.id)})
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.json()["data"], [])

    def test_deleting_synced_door_code_fails_when_lock_unreachable(self):
        from integrations_zwavejs.manager import ZwavejsCommandError

        Entity.objects.create(
            entity_id="lock.front_door",
            domain="lock",
            name="Front Door",
            attributes={"zwavejs": {"node_id": 5}},
            source="zwavejs",
        )
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=None,
            label="Slot 1",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=None,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=code,
            lock_entity_id="lock.front_door",
            slot_index=1,
        )

        fake_gw = MagicMock()
        fake_gw.invoke_cc_api.side_effect = ZwavejsCommandError("Z-Wave error 202: timeout")

        url = reverse("door-code-detail", args=[code.id])
        with patch("locks.views.door_codes.default_zwavejs_gateway", fake_gw):
            response = self.client.delete(url, {"reauth_password": "pass"}, format="json")

        # Should fail with 502 (gateway error).
        self.assertEqual(response.status_code, 502)

        # DB state should be unchanged (code still active, delete failed).
        code.refresh_from_db()
        self.assertTrue(code.is_active)
        self.assertTrue(
            DoorCodeLockAssignment.objects.filter(door_code=code, lock_entity_id="lock.front_door").exists()
        )

    def test_non_admin_cannot_delete_door_code(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="User code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        url = reverse("door-code-detail", args=[code.id])
        response = self.client.delete(
            url,
            {"reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_code_must_be_digits_only(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Bad code",
                "code": "12ab",
                "code_type": DoorCode.CodeType.PERMANENT,
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_code_must_be_4_to_8_digits(self):
        url = reverse("door-codes")

        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Too short",
                "code": "123",
                "code_type": DoorCode.CodeType.PERMANENT,
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Too long",
                "code": "123456789",
                "code_type": DoorCode.CodeType.PERMANENT,
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_reauth_password_required_for_create(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "User code",
                "code": "1234",
                "code_type": DoorCode.CodeType.PERMANENT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_reauth_password_must_match(self):
        url = reverse("door-codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "User code",
                "code": "1234",
                "code_type": DoorCode.CodeType.PERMANENT,
                "reauth_password": "wrong-password",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # Synced code update restrictions
    # ------------------------------------------------------------------

    def _create_synced_code(self):
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            encrypted_pin=None,
            label="Slot 1",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=None,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=code,
            lock_entity_id="lock.front_door",
            slot_index=1,
        )
        return code

    def test_synced_code_rejects_restricted_field_updates(self):
        code = self._create_synced_code()
        url = reverse("door-code-detail", args=[code.id])

        response = self.client.patch(
            url,
            {
                "max_uses": 5,
                "is_active": False,
                "lock_entity_ids": ["lock.back_door"],
                "days_of_week": 1,
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        details = response.json()["error"]["details"]
        for field in ("max_uses", "is_active", "lock_entity_ids", "days_of_week"):
            self.assertIn(field, details, f"Expected validation error for {field}")

    def test_synced_code_allows_label_update(self):
        code = self._create_synced_code()
        url = reverse("door-code-detail", args=[code.id])

        response = self.client.patch(
            url,
            {"label": "Front door slot", "reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["label"], "Front door slot")

    def test_synced_code_rejects_code_change(self):
        code = self._create_synced_code()
        url = reverse("door-code-detail", args=[code.id])

        response = self.client.patch(
            url,
            {"code": "9999", "reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        details = response.json()["error"]["details"]
        self.assertIn("code", details)

    def test_manual_code_still_allows_all_fields(self):
        code = DoorCode.objects.create(
            user=self.user,
            encrypted_pin="not-used-here",
            label="Manual code",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=code,
            lock_entity_id="lock.front_door",
        )
        url = reverse("door-code-detail", args=[code.id])

        response = self.client.patch(
            url,
            {
                "label": "Updated",
                "max_uses": 10,
                "lock_entity_ids": ["lock.back_door"],
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()["data"]
        self.assertEqual(body["label"], "Updated")
        self.assertEqual(body["max_uses"], 10)
        self.assertEqual(body["lock_entity_ids"], ["lock.back_door"])
