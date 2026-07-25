from __future__ import annotations

from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from integrations_home_assistant.connection import clear_cached_connection
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.tests.settings_test_utils import EncryptionTestMixin


class _FakeStatusClient:
    """Stands in for ``impl._StatusClient``: a reachable Home Assistant."""

    last_status_code = 200
    last_content_type = "application/json"
    last_body_preview = ""

    def check_api_running(self) -> bool:
        return True

    def close(self) -> None:
        return None


class HomeAssistantStatusCacheWarmupTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-status@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        AlarmSettingsProfile.objects.update(is_active=False)
        self.profile = AlarmSettingsProfile.objects.create(name="HA Status Test Profile", is_active=True)

        # Store HA config in DB
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

    @override_settings(ALLOW_HOME_ASSISTANT_IN_TESTS=True)
    @patch("integrations_home_assistant.impl._build_status_client")
    def test_status_endpoint_warms_cache_from_active_profile(self, mock_build_client):
        clear_cached_connection()
        mock_build_client.return_value = _FakeStatusClient()

        response = self.client.get(reverse("ha-status"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["configured"], True)
        self.assertEqual(body["data"]["reachable"], True)
        self.assertEqual(body["data"]["base_url"], "http://homeassistant.local:8123")
