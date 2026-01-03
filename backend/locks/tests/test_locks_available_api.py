from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsProfile


class LocksAvailableApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="locks@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        # Use get_or_create to avoid duplicate key errors
        self.profile, _ = AlarmSettingsProfile.objects.get_or_create(
            name="Default", defaults={"is_active": True}
        )

    def test_available_locks_requires_auth(self):
        client = APIClient()
        url = reverse("locks-available")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_available_locks_returns_error_when_ha_not_configured(self):
        url = reverse("locks-available")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["status"], "service_unavailable")

    @patch("locks.views.sync.ha_gateway")
    def test_available_locks_returns_list_when_ha_configured(self, mock_gateway):
        mock_gateway.ensure_available.return_value = None

        # Mock the lock sync use case response
        with patch("locks.views.sync.lock_sync.fetch_available_locks") as mock_fetch:
            mock_fetch.return_value = [
                {"entity_id": "lock.front_door", "name": "Front Door"},
                {"entity_id": "lock.back_door", "name": "Back Door"},
            ]

            url = reverse("locks-available")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("data", response.data)
            self.assertEqual(len(response.data["data"]), 2)
