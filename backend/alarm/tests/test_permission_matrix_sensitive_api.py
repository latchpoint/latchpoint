from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings


class SensitiveApiPermissionMatrixTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="matrix-user@example.com", password="pass")
        self.admin = User.objects.create_user(email="matrix-admin@example.com", password="pass", is_staff=True)

        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)

        self.user_client = APIClient()
        self.user_client.force_authenticate(self.user)

        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)

        AlarmSettingsProfile.objects.update(is_active=False)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            mqtt_connection={"enabled": True, "host": "mqtt.local", "port": 1883},
            zwavejs_connection={"enabled": True, "ws_url": "ws://zwavejs.local:3000"},
            zigbee2mqtt={"enabled": True, "base_topic": "zigbee2mqtt"},
        )

    def _assert_get_matrix(self, *, url_name: str):
        url = reverse(url_name)
        self.assertEqual(APIClient().get(url).status_code, 401)
        self.assertEqual(self.user_client.get(url).status_code, 403)
        self.assertEqual(self.admin_client.get(url).status_code, 200)

    def test_sensitive_get_endpoints_have_explicit_401_403_200_matrix(self):
        for url_name in (
            "system-config-list",
            "debug-logs",
            "scheduler-status",
            "mqtt-settings",
            "ha-settings",
            "zwavejs-settings",
            "zigbee2mqtt-settings",
        ):
            with self.subTest(url_name=url_name):
                self._assert_get_matrix(url_name=url_name)

    @patch("integrations_zigbee2mqtt.views.sync_devices_via_mqtt")
    def test_zigbee2mqtt_sync_has_explicit_401_403_200_matrix(self, mock_sync_devices):
        mock_sync_devices.return_value = {"ok": True, "count": 1, "created": 1, "updated": 0}

        url = reverse("zigbee2mqtt-devices-sync")
        self.assertEqual(APIClient().post(url, data={}, format="json").status_code, 401)
        self.assertEqual(self.user_client.post(url, data={}, format="json").status_code, 403)

        response = self.admin_client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["ok"], True)

    @patch("integrations_zwavejs.views.sync_entities_from_zwavejs")
    @patch("integrations_zwavejs.views.zwavejs_gateway")
    def test_zwavejs_sync_has_explicit_401_403_200_matrix(self, mock_gateway, mock_sync_entities):
        mock_gateway.apply_settings.return_value = None
        mock_gateway.ensure_connected.return_value = None
        mock_sync_entities.return_value = {"imported": 1, "updated": 0}

        url = reverse("zwavejs-entities-sync")
        self.assertEqual(APIClient().post(url, data={}, format="json").status_code, 401)
        self.assertEqual(self.user_client.post(url, data={}, format="json").status_code, 403)

        response = self.admin_client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["imported"], 1)
