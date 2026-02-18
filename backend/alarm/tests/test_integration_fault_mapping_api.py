from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment
from alarm.gateways.home_assistant import HomeAssistantNotReachable
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings


class IntegrationFaultMappingApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="faults-user@example.com", password="pass")
        self.admin = User.objects.create_user(email="faults-admin@example.com", password="pass")

        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)

        self.user_client = APIClient()
        self.user_client.force_authenticate(self.user)

        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)

        AlarmSettingsProfile.objects.update(is_active=False)
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            profile,
            mqtt_connection={"enabled": True, "host": "mqtt.local", "port": 1883},
            zwavejs_connection={"enabled": True, "ws_url": "ws://zwavejs.local:3000"},
        )

    def test_mqtt_test_connection_invalid_config_maps_to_validation_error_envelope(self):
        response = self.admin_client.post(
            reverse("mqtt-test"),
            data={"host": "mqtt.local"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["status"], "validation_error")
        self.assertIn("details", body["error"])
        self.assertIn("port", body["error"]["details"])

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_home_assistant_unavailable_maps_to_service_unavailable(self, mock_gateway):
        mock_gateway.ensure_available.side_effect = HomeAssistantNotReachable("upstream unavailable")

        response = self.user_client.get(reverse("ha-entities"))
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["status"], "service_unavailable")
        self.assertEqual(body["error"]["gateway"], "Home Assistant")

    @patch("integrations_zwavejs.views.sync_entities_from_zwavejs")
    @patch("integrations_zwavejs.views.zwavejs_gateway")
    def test_zwavejs_runtime_error_maps_to_service_unavailable(self, mock_gateway, mock_sync):
        mock_gateway.apply_settings.return_value = None
        mock_gateway.ensure_connected.return_value = None
        mock_sync.side_effect = RuntimeError("unexpected runtime failure")

        response = self.admin_client.post(reverse("zwavejs-entities-sync"), data={}, format="json")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["status"], "service_unavailable")
        self.assertIn("Failed to sync Z-Wave JS entities", body["error"]["message"])

    @patch("integrations_zigbee2mqtt.views.sync_devices_via_mqtt")
    def test_zigbee2mqtt_timeout_maps_to_timeout_envelope(self, mock_sync):
        mock_sync.side_effect = TimeoutError("Timed out waiting for Zigbee2MQTT devices.")

        response = self.admin_client.post(reverse("zigbee2mqtt-devices-sync"), data={}, format="json")
        self.assertEqual(response.status_code, 504)
        body = response.json()
        self.assertEqual(body["error"]["status"], "timeout")

    @patch("integrations_zigbee2mqtt.views.sync_devices_via_mqtt")
    def test_zigbee2mqtt_unexpected_error_maps_to_service_unavailable(self, mock_sync):
        mock_sync.side_effect = RuntimeError("boom")

        response = self.admin_client.post(reverse("zigbee2mqtt-devices-sync"), data={}, format="json")
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["status"], "service_unavailable")
