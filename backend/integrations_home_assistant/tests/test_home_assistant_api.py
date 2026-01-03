from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings


class HomeAssistantEntitiesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-entities@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_entities_endpoint_requires_auth(self):
        client = APIClient()
        url = reverse("ha-entities")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_entities_endpoint_returns_error_when_not_configured(self):
        url = reverse("ha-entities")
        response = self.client.get(url)
        # Returns 400 (not configured) or 503 (not reachable) depending on gateway state
        self.assertIn(response.status_code, [400, 503])
        self.assertIn("error", response.json())

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_entities_endpoint_returns_list_when_configured(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None
        mock_gateway.list_entities.return_value = [
            {"entity_id": "binary_sensor.front_door", "state": "off"},
            {"entity_id": "light.living_room", "state": "on"},
        ]

        url = reverse("ha-entities")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 2)


class HomeAssistantNotifyServicesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-notify@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_notify_services_requires_auth(self):
        client = APIClient()
        url = reverse("ha-notify-services")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_notify_services_returns_error_when_not_configured(self):
        url = reverse("ha-notify-services")
        response = self.client.get(url)
        # Returns 400 (not configured) or 503 (not reachable) depending on gateway state
        self.assertIn(response.status_code, [400, 503])
        self.assertIn("error", response.json())

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_notify_services_returns_list_when_configured(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None
        mock_gateway.list_notify_services.return_value = [
            "notify.notify",
            "notify.mobile_app_phone",
        ]

        url = reverse("ha-notify-services")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 2)


class HomeAssistantSettingsApiPermissionTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha-settings-user@example.com", password="pass")
        self.admin = User.objects.create_user(email="ha-settings-admin@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=self.admin, role=role)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def test_get_settings_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("ha-settings")
        response = client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_patch_settings_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("ha-settings")
        response = client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_get_settings(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        url = reverse("ha-settings")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("data", response.json())

    def test_patch_settings_requires_base_url_and_token_when_enabled(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        url = reverse("ha-settings")
        response = client.patch(url, data={"enabled": True}, format="json")
        self.assertEqual(response.status_code, 400)
        # Validates either base_url or token is required
        message = response.json()["error"]["message"].lower()
        self.assertTrue("base_url" in message or "token" in message)
