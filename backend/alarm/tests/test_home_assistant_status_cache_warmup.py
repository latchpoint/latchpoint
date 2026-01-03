from __future__ import annotations

import json
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings
from integrations_home_assistant.connection import clear_cached_connection


class _DummyResponse:
    def __init__(self, *, status: int, headers: dict[str, str] | None = None, body: bytes = b""):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def read(self, n: int = -1) -> bytes:
        if n == -1:
            return self._body
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class HomeAssistantStatusCacheWarmupTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-status@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        # Deactivate any existing profiles to ensure test isolation
        AlarmSettingsProfile.objects.update(is_active=False)
        self.profile = AlarmSettingsProfile.objects.create(name="HA Status Test Profile", is_active=True)
        set_profile_settings(
            self.profile,
            home_assistant_connection={
                "enabled": True,
                "base_url": "http://homeassistant.local:8123",
                "token": "supersecret",
                "connect_timeout_seconds": 2,
            },
        )

    @override_settings(ALLOW_HOME_ASSISTANT_IN_TESTS=True)
    @patch("alarm.gateways.home_assistant.DefaultHomeAssistantGateway._import_client", return_value=None)
    @patch("alarm.gateways.home_assistant.urlopen")
    def test_status_endpoint_warms_cache_from_active_profile(self, mock_urlopen, _mock_import_client):
        clear_cached_connection()
        mock_urlopen.return_value = _DummyResponse(
            status=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=json.dumps({"message": "API running."}).encode("utf-8"),
        )

        response = self.client.get(reverse("ha-status"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["configured"], True)
        self.assertEqual(body["data"]["reachable"], True)
        self.assertEqual(body["data"]["base_url"], "http://homeassistant.local:8123")
