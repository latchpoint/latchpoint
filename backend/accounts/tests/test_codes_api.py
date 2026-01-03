from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User, UserCode, UserCodeAllowedState


class CodesApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.client.force_authenticate(self.admin)

    def test_list_codes_for_self(self):
        UserCode.objects.create(
            user=self.admin,
            code_hash="not-used-here",
            label="Admin code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )

        url = reverse("codes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json()["data"], list)

    def test_admin_can_create_code_for_other_user_with_allowed_states(self):
        url = reverse("codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "User code",
                "code": "1234",
                "code_type": UserCode.CodeType.PERMANENT,
                "allowed_states": [UserCodeAllowedState.AlarmState.ARMED_AWAY],
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["data"]["user_id"], str(self.user.id))
        self.assertEqual(body["data"]["allowed_states"], [UserCodeAllowedState.AlarmState.ARMED_AWAY])

    def test_cannot_set_active_range_on_non_temporary(self):
        url = reverse("codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Bad code",
                "code": "1234",
                "code_type": UserCode.CodeType.PERMANENT,
                "start_at": "2025-01-01T00:00:00Z",
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_can_create_temporary_code_with_day_and_time_restrictions(self):
        url = reverse("codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "Sat morning",
                "code": "1234",
                "code_type": UserCode.CodeType.TEMPORARY,
                "days_of_week": 1 << 5,  # Saturday only (Mon=0)
                "window_start": "08:00",
                "window_end": "10:00",
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["data"]["code_type"], UserCode.CodeType.TEMPORARY)
        self.assertEqual(body["data"]["days_of_week"], 1 << 5)
        self.assertEqual(body["data"]["window_start"], "08:00:00")
        self.assertEqual(body["data"]["window_end"], "10:00:00")

    def test_admin_can_list_codes_for_other_user(self):
        code = UserCode.objects.create(
            user=self.user,
            code_hash="not-used-here",
            label="User code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        UserCodeAllowedState.objects.create(code=code, state=UserCodeAllowedState.AlarmState.ARMED_HOME)

        url = reverse("codes")
        response = self.client.get(url, {"user_id": str(self.user.id)})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["user_id"], str(self.user.id))
        self.assertEqual(body["data"][0]["allowed_states"], [UserCodeAllowedState.AlarmState.ARMED_HOME])

    def test_non_admin_can_read_own_code_detail(self):
        code = UserCode.objects.create(
            user=self.user,
            code_hash="not-used-here",
            label="User code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        url = reverse("code-detail", args=[code.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["user_id"], str(self.user.id))

    def test_non_admin_cannot_read_other_user_code_detail(self):
        other_code = UserCode.objects.create(
            user=self.admin,
            code_hash="not-used-here",
            label="Admin code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        url = reverse("code-detail", args=[other_code.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_create_code(self):
        self.client.force_authenticate(self.user)
        url = reverse("codes")
        response = self.client.post(
            url,
            {
                "user_id": str(self.user.id),
                "label": "User code",
                "code": "1234",
                "code_type": UserCode.CodeType.PERMANENT,
                "reauth_password": "pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_update_code(self):
        code = UserCode.objects.create(
            user=self.user,
            code_hash="not-used-here",
            label="User code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        self.client.force_authenticate(self.user)
        url = reverse("code-detail", args=[code.id])
        response = self.client.patch(
            url,
            {"label": "New", "reauth_password": "pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
