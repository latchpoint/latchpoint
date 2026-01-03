from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from integrations_home_assistant.models import HomeAssistantMqttAlarmEntityStatus
from alarm.state_machine.settings import get_setting_json
from alarm.tests.settings_test_utils import set_profile_settings


class MqttApiTests(APITestCase):
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
            mqtt_connection={
                "enabled": True,
                "host": "mqtt.local",
                "port": 1883,
                "username": "u",
                "password": "supersecret",
                "use_tls": False,
                "tls_insecure": False,
                "client_id": "latchpoint-alarm",
                "keepalive_seconds": 30,
                "connect_timeout_seconds": 5,
            },
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

    def test_mqtt_password_is_masked_in_settings_profile_detail(self):
        url = reverse("alarm-settings-profile-detail", args=[self.profile.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        entries = response.json()["data"]["entries"]
        mqtt_entries = [e for e in entries if e["key"] == "mqtt_connection"]
        self.assertEqual(len(mqtt_entries), 1)
        value = mqtt_entries[0]["value"]
        self.assertNotIn("password", value)
        self.assertEqual(value["has_password"], True)

    def test_mqtt_password_is_masked_in_mqtt_settings_endpoint(self):
        url = reverse("mqtt-settings")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("password", body["data"])
        self.assertEqual(body["data"]["has_password"], True)

    def test_patch_mqtt_settings_preserves_password_when_omitted(self):
        url = reverse("mqtt-settings")
        response = self.client.patch(url, data={"host": "mqtt2.local"}, format="json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("password", body["data"])
        self.assertEqual(body["data"]["has_password"], True)

    def test_disabling_mqtt_disables_zigbee2mqtt_and_frigate(self):
        url = reverse("mqtt-settings")
        response = self.client.patch(url, data={"enabled": False}, format="json")
        self.assertEqual(response.status_code, 200)

        self.profile.refresh_from_db()
        z2m = get_setting_json(self.profile, "zigbee2mqtt") or {}
        frigate = get_setting_json(self.profile, "frigate") or {}
        self.assertEqual(bool(z2m.get("enabled")), False)
        self.assertEqual(bool(frigate.get("enabled")), False)

    def test_cannot_enable_zigbee2mqtt_or_frigate_when_mqtt_disabled(self):
        response = self.client.patch(reverse("mqtt-settings"), data={"enabled": False}, format="json")
        self.assertEqual(response.status_code, 200)

        resp_z2m = self.client.patch(reverse("zigbee2mqtt-settings"), data={"enabled": True}, format="json")
        self.assertEqual(resp_z2m.status_code, 400)

        resp_frigate = self.client.patch(reverse("frigate-settings"), data={"enabled": True}, format="json")
        self.assertEqual(resp_frigate.status_code, 400)

    def test_publish_discovery_endpoint_calls_publish(self):
        url = reverse("integrations-ha-mqtt-alarm-entity-publish-discovery")
        with patch("integrations_home_assistant.mqtt_alarm_entity.mqtt_connection_manager.publish") as publish:
            response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(publish.called)

    def test_publish_discovery_persists_status_timestamps(self):
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
