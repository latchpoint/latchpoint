from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from locks.models import DoorCode, DoorCodeLockAssignment


class DoorCodesApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.client.force_authenticate(self.admin)

    def test_list_door_codes_for_self(self):
        DoorCode.objects.create(
            user=self.admin,
            code_hash="not-used-here",
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
            code_hash="not-used-here",
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
            code_hash="not-used-here",
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
            code_hash="not-used-here",
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
            code_hash="not-used-here",
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
            code_hash="not-used-here",
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
            code_hash="not-used-here",
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
            code_hash="not-used-here",
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

    def test_deleting_synced_door_code_dismisses_slot_instead_of_hard_delete(self):
        code = DoorCode.objects.create(
            user=self.user,
            source=DoorCode.Source.SYNCED,
            code_hash=None,
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

        url = reverse("door-code-detail", args=[code.id])
        response = self.client.delete(url, {"reauth_password": "pass"}, format="json")
        self.assertEqual(response.status_code, 204)

        code.refresh_from_db()
        self.assertFalse(code.is_active)
        assignment = DoorCodeLockAssignment.objects.get(door_code=code, lock_entity_id="lock.front_door")
        self.assertTrue(assignment.sync_dismissed)

        list_url = reverse("door-codes")
        list_resp = self.client.get(list_url, {"user_id": str(self.user.id)})
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(list_resp.json()["data"], [])

    def test_non_admin_cannot_delete_door_code(self):
        code = DoorCode.objects.create(
            user=self.user,
            code_hash="not-used-here",
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
