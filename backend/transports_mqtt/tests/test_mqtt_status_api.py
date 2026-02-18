from __future__ import annotations

from unittest.mock import Mock, patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings
from transports_mqtt.manager import MqttNotReachable


class MqttStatusApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="mqtt-status@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.filter(name="Default").first()
        if self.profile is None:
            self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        else:
            AlarmSettingsProfile.objects.update(is_active=False)
            self.profile.is_active = True
            self.profile.save(update_fields=["is_active"])
        set_profile_settings(
            self.profile,
            mqtt_connection={
                "enabled": True,
                "host": "mqtt.local",
                "port": 1883,
                "username": "",
                "password": "",
                "use_tls": False,
                "tls_insecure": False,
                "client_id": "latchpoint-test",
                "keepalive_seconds": 30,
                "connect_timeout_seconds": 5,
            },
        )

    def test_status_requires_auth(self):
        response = APIClient().get(reverse("mqtt-status"))
        self.assertEqual(response.status_code, 401)

    @patch("transports_mqtt.views.mqtt_gateway")
    def test_status_returns_connection_snapshot(self, mock_gateway):
        mock_status = Mock()
        mock_status.as_dict.return_value = {
            "configured": True,
            "enabled": True,
            "connected": True,
            "last_connect_at": None,
            "last_disconnect_at": None,
            "last_error": None,
        }
        mock_gateway.get_status.return_value = mock_status

        response = self.client.get(reverse("mqtt-status"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["connected"], True)
        self.assertEqual(body["data"]["enabled"], True)
        self.assertEqual(mock_gateway.apply_settings.called, True)

    @patch("transports_mqtt.views.mqtt_gateway")
    def test_status_returns_standard_error_when_gateway_unreachable(self, mock_gateway):
        mock_gateway.apply_settings.side_effect = MqttNotReachable("Broker not reachable.")

        response = self.client.get(reverse("mqtt-status"))
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "service_unavailable")
        self.assertEqual(body["error"]["gateway"], "MQTT")
