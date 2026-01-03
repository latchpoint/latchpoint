from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import Entity


class HomeAssistantStatusApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ha@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_status_not_configured(self):
        url = reverse("ha-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["data"]["configured"])
        self.assertFalse(body["data"]["reachable"])

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_status_reachable(self, mock_gateway):
        class _Status:
            def as_dict(self):
                return {"configured": True, "reachable": True, "base_url": "http://ha:8123", "error": None}

        mock_gateway.get_status.return_value = _Status()
        url = reverse("ha-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["data"]["configured"])
        self.assertTrue(body["data"]["reachable"])

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_entities_returns_data(self, mock_gateway):
        mock_gateway.ensure_available.return_value = object()
        mock_gateway.list_entities.return_value = [
            {
                "entity_id": "binary_sensor.front_door",
                "state": "off",
                "attributes": {"friendly_name": "Front Door", "device_class": "door"},
                "last_changed": "2025-01-01T00:00:00Z",
            }
        ]
        url = reverse("ha-entities")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["entity_id"], "binary_sensor.front_door")

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_entities_handles_list_failure(self, mock_gateway):
        mock_gateway.ensure_available.return_value = object()
        mock_gateway.list_entities.side_effect = RuntimeError("boom")
        url = reverse("ha-entities")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["error"]["status"], "service_unavailable")
        self.assertEqual(body["error"]["message"], "Failed to fetch Home Assistant entities.")

    @patch("integrations_home_assistant.views.ha_gateway")
    def test_notify_services_returns_data(self, mock_gateway):
        mock_gateway.ensure_available.return_value = object()
        mock_gateway.list_notify_services.return_value = ["notify.notify", "notify.mobile_app_phone"]

        url = reverse("ha-notify-services")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], ["notify.notify", "notify.mobile_app_phone"])

    @patch("alarm.views.entities.ha_gateway")
    def test_entity_sync_imports_entities(self, mock_gateway):
        mock_gateway.ensure_available.return_value = object()
        mock_gateway.list_entities.return_value = [
            {
                "entity_id": "binary_sensor.front_door",
                "domain": "binary_sensor",
                "name": "Front Door",
                "state": "off",
                "device_class": "door",
                "last_changed": "2025-01-01T00:00:00Z",
            }
        ]

        url = reverse("alarm-entities-sync")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["imported"], 1)
        self.assertEqual(body["data"]["updated"], 0)

        entity = Entity.objects.get(entity_id="binary_sensor.front_door")
        self.assertEqual(entity.domain, "binary_sensor")
        self.assertEqual(entity.name, "Front Door")
        self.assertEqual(entity.last_state, "off")
