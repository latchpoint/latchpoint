from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from integrations_home_assistant.models import HomeAssistantMqttAlarmEntityStatus
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.tests.settings_test_utils import EncryptionTestMixin, set_profile_settings


class MqttApiTests(EncryptionTestMixin, APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="mqtt@example.com", password="pass")
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

        self.profile = AlarmSettingsProfile.objects.filter(name="Default").first()
        if self.profile is None:
            self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        else:
            AlarmSettingsProfile.objects.update(is_active=False)
            self.profile.is_active = True
            self.profile.save(update_fields=["is_active"])
        set_profile_settings(
            self.profile,
            home_assistant_alarm_entity={
                "enabled": True,
                "entity_name": "Latchpoint",
                "also_rename_in_home_assistant": True,
                "ha_entity_id": "alarm_control_panel.latchpoint_alarm",
            },
            zigbee2mqtt={
                "enabled": True,
                "base_topic": "zigbee2mqtt",
                "allowlist": [],
                "denylist": [],
            },
            frigate={
                "enabled": True,
                "events_topic": "frigate/events",
                "retention_seconds": 3600,
            },
        )

    def test_mqtt_password_is_masked_in_mqtt_settings_endpoint(self):
        # Store MQTT config with encrypted password via model method
        definition = ALARM_PROFILE_SETTINGS_BY_KEY["mqtt"]
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=self.profile,
            key="mqtt",
            defaults={"value": definition.default, "value_type": definition.value_type},
        )
        entry.set_value_with_encryption(
            {
                "enabled": True,
                "host": "mqtt.local",
                "port": 1883,
                "username": "u",
                "password": "supersecret",
                "use_tls": False,
                "tls_insecure": False,
                "client_id": "latchpoint-alarm",
            }
        )

        url = reverse("mqtt-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("password", body["data"])
        self.assertEqual(body["data"]["has_password"], True)

    @patch("transports_mqtt.manager.MqttConnectionManager.apply_settings")
    def test_patch_mqtt_settings_accepts_operational_settings(self, _mock_apply):
        url = reverse("mqtt-settings")
        response = self.client.patch(url, data={"keepalive_seconds": 60}, format="json")
        self.assertEqual(response.status_code, 200)
        _mock_apply.assert_called_once()

    @patch("transports_mqtt.manager.MqttConnectionManager.apply_settings")
    def test_publish_discovery_endpoint_calls_publish(self, _mock_apply):
        # Enable MQTT in DB so _mqtt_enabled() passes
        definition = ALARM_PROFILE_SETTINGS_BY_KEY["mqtt"]
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=self.profile,
            key="mqtt",
            defaults={"value": definition.default, "value_type": definition.value_type},
        )
        entry.set_value_with_encryption({"enabled": True, "host": "mqtt.local"})

        url = reverse("integrations-ha-mqtt-alarm-entity-publish-discovery")
        with patch("integrations_home_assistant.mqtt_alarm_entity.mqtt_connection_manager.publish") as publish:
            response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(publish.called)

    @patch("transports_mqtt.manager.MqttConnectionManager.apply_settings")
    def test_publish_discovery_persists_status_timestamps(self, _mock_apply):
        definition = ALARM_PROFILE_SETTINGS_BY_KEY["mqtt"]
        entry, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=self.profile,
            key="mqtt",
            defaults={"value": definition.default, "value_type": definition.value_type},
        )
        entry.set_value_with_encryption({"enabled": True, "host": "mqtt.local"})

        url = reverse("integrations-ha-mqtt-alarm-entity-publish-discovery")
        with patch("integrations_home_assistant.mqtt_alarm_entity.mqtt_connection_manager.publish"):
            response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)
        status = HomeAssistantMqttAlarmEntityStatus.objects.filter(profile=self.profile).first()
        self.assertIsNotNone(status)
        assert status is not None
        self.assertIsNotNone(status.last_discovery_publish_at)
        self.assertIsNotNone(status.last_availability_publish_at)
        self.assertIsNotNone(status.last_state_publish_at)


class MqttApiPermissionsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="nonadmin-mqtt@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_non_admin_cannot_update_mqtt_settings(self):
        url = reverse("mqtt-settings")
        response = self.client.patch(url, data={"host": "mqtt.local"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_test_mqtt_connection(self):
        url = reverse("mqtt-test")
        response = self.client.post(url, data={"host": "mqtt.local", "port": 1883}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_publish_discovery(self):
        url = reverse("integrations-ha-mqtt-alarm-entity-publish-discovery")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_non_admin_cannot_update_alarm_entity_settings(self):
        url = reverse("integrations-ha-mqtt-alarm-entity")
        response = self.client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 403)
