from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import Entity


class EntitiesApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="entities@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_get_entities_requires_auth(self):
        client = APIClient()
        url = reverse("alarm-entities")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_get_entities_returns_list(self):
        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front Door",
            last_state="off",
        )
        Entity.objects.create(
            entity_id="binary_sensor.motion",
            domain="binary_sensor",
            name="Motion",
            last_state="on",
        )

        url = reverse("alarm-entities")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body["data"], list)
        self.assertEqual(len(body["data"]), 2)

    def test_entity_sync_requires_auth(self):
        client = APIClient()
        url = reverse("alarm-entities-sync")
        response = client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_entity_sync_returns_503_when_ha_not_configured(self):
        # By default, HA is not configured, so sync should return a gateway error
        url = reverse("alarm-entities-sync")
        response = self.client.post(url, data={}, format="json")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["status"], "service_unavailable")
