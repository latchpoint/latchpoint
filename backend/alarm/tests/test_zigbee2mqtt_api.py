from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserCode, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
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
