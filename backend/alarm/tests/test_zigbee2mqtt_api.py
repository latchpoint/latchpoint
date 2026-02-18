from __future__ import annotations

from unittest.mock import Mock, patch

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsProfile, Entity
from alarm.tests.settings_test_utils import set_profile_settings


class Zigbee2mqttApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="z2m@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        UserCode.objects.create(
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
            mqtt_connection={"enabled": True, "host": "mqtt.local", "port": 1883},
            zigbee2mqtt={
                "enabled": True,
                "base_topic": "zigbee2mqtt",
                "allowlist": [],
                "denylist": [],
            },
        )


class Zigbee2mqttApiPermissionsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="nonadmin-z2m@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_non_admin_cannot_update_settings(self):
        url = reverse("zigbee2mqtt-settings")
        response = self.client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 403)


class Zigbee2mqttEndpointApiTests(Zigbee2mqttApiTests):
    def test_status_requires_auth(self):
        response = APIClient().get(reverse("zigbee2mqtt-status"))
        self.assertEqual(response.status_code, 401)

    @patch("integrations_zigbee2mqtt.views.apply_runtime_settings_from_active_profile")
    @patch("integrations_zigbee2mqtt.views.mqtt_connection_manager.get_status")
    @patch("integrations_zigbee2mqtt.views.get_last_sync")
    @patch("integrations_zigbee2mqtt.views.get_last_seen_at")
    @patch("integrations_zigbee2mqtt.views.get_last_state")
    def test_status_returns_runtime_payload(
        self,
        mock_get_last_state,
        mock_get_last_seen_at,
        mock_get_last_sync,
        mock_get_mqtt_status,
        _mock_apply_runtime_settings,
    ):
        mock_get_last_state.return_value = "online"
        mock_get_last_seen_at.return_value = timezone.now().isoformat()
        mock_status = Mock()
        mock_status.connected = True
        mock_status.as_dict.return_value = {
            "configured": True,
            "enabled": True,
            "connected": True,
            "last_connect_at": None,
            "last_disconnect_at": None,
            "last_error": None,
        }
        mock_get_mqtt_status.return_value = mock_status
        mock_sync = Mock()
        mock_sync.as_dict.return_value = {
            "last_sync_at": timezone.now().isoformat(),
            "last_device_count": 2,
            "last_error": None,
        }
        mock_get_last_sync.return_value = mock_sync

        response = self.client.get(reverse("zigbee2mqtt-status"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["enabled"], True)
        self.assertEqual(body["data"]["connected"], True)
        self.assertEqual(body["data"]["base_topic"], "zigbee2mqtt")
        self.assertIn("mqtt", body["data"])
        self.assertIn("sync", body["data"])

    def test_devices_requires_auth(self):
        response = APIClient().get(reverse("zigbee2mqtt-devices"))
        self.assertEqual(response.status_code, 401)

    def test_devices_returns_entity_list(self):
        Entity.objects.create(
            entity_id="z2m_switch.0x00124b0018e2abcd_state",
            domain="switch",
            name="Front Light",
            source="zigbee2mqtt",
            attributes={},
        )
        Entity.objects.create(
            entity_id="sensor.not_z2m",
            domain="sensor",
            name="Other",
            source="home_assistant",
            attributes={},
        )

        response = self.client.get(reverse("zigbee2mqtt-devices"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["source"], "zigbee2mqtt")

    def test_devices_sync_requires_auth(self):
        response = APIClient().post(reverse("zigbee2mqtt-devices-sync"), data={}, format="json")
        self.assertEqual(response.status_code, 401)

    @patch("integrations_zigbee2mqtt.views.sync_devices_via_mqtt")
    def test_devices_sync_returns_summary(self, mock_sync_devices_via_mqtt):
        mock_sync_devices_via_mqtt.return_value = {
            "ok": True,
            "count": 3,
            "created": 2,
            "updated": 1,
        }

        response = self.client.post(reverse("zigbee2mqtt-devices-sync"), data={}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["ok"], True)
        self.assertEqual(body["data"]["count"], 3)

    @patch("integrations_zigbee2mqtt.views.sync_devices_via_mqtt")
    def test_devices_sync_returns_standard_timeout_error(self, mock_sync_devices_via_mqtt):
        mock_sync_devices_via_mqtt.side_effect = TimeoutError("Timed out waiting for Zigbee2MQTT devices.")

        response = self.client.post(reverse("zigbee2mqtt-devices-sync"), data={}, format="json")
        self.assertEqual(response.status_code, 504)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "timeout")
