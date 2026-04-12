from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.tests.settings_test_utils import EncryptionTestMixin


class HomeAssistantSettingsApiTests(EncryptionTestMixin, APITestCase):
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

    def test_home_assistant_token_is_masked_in_home_assistant_settings_endpoint(self):
        # Store a token via the model encryption method
        definition = ALARM_PROFILE_SETTINGS_BY_KEY["home_assistant"]
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=self.profile,
            key="home_assistant",
            defaults={"value": definition.default, "value_type": definition.value_type},
        )
        entry.set_value_with_encryption(
            {
                "enabled": True,
                "base_url": "http://homeassistant.local:8123",
                "token": "supersecret",
            }
        )

        url = reverse("ha-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("token", body["data"])
        self.assertEqual(body["data"]["has_token"], True)

    def test_patch_home_assistant_settings_accepts_operational_settings(self):
        url = reverse("ha-settings")
        response = self.client.patch(url, data={"connect_timeout_seconds": 5}, format="json")
        self.assertEqual(response.status_code, 200)


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
