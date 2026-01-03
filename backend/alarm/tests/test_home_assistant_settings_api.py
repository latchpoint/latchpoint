from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings


class HomeAssistantSettingsApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-settings@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("1234"),
            label="Test Code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )

        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            home_assistant_connection={
                "enabled": True,
                "base_url": "http://homeassistant.local:8123",
                "token": "supersecret",
                "connect_timeout_seconds": 2,
            },
        )

    def test_home_assistant_token_is_masked_in_settings_profile_detail(self):
        url = reverse("alarm-settings-profile-detail", args=[self.profile.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        entries = response.json()["data"]["entries"]
        ha_entries = [e for e in entries if e["key"] == "home_assistant_connection"]
        self.assertEqual(len(ha_entries), 1)
        value = ha_entries[0]["value"]
        self.assertNotIn("token", value)
        self.assertEqual(value["has_token"], True)

    def test_home_assistant_token_is_masked_in_home_assistant_settings_endpoint(self):
        url = reverse("ha-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("token", body["data"])
        self.assertEqual(body["data"]["has_token"], True)

    def test_patch_home_assistant_settings_preserves_token_when_omitted(self):
        url = reverse("ha-settings")
        response = self.client.patch(url, data={"base_url": "http://ha2.local:8123"}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("token", body["data"])
        self.assertEqual(body["data"]["has_token"], True)

    def test_patch_home_assistant_settings_requires_encryption_key_when_setting_token(self):
        url = reverse("ha-settings")
        with patch("integrations_home_assistant.views.can_encrypt", return_value=False):
            response = self.client.patch(url, data={"token": "newtoken"}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["status"], "configuration_error")


class HomeAssistantSettingsApiPermissionsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="nonadmin-ha-settings@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_non_admin_cannot_update_home_assistant_settings(self):
        url = reverse("ha-settings")
        response = self.client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_read_home_assistant_settings(self):
        url = reverse("ha-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
