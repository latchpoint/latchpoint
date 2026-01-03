from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import SystemConfig


class SystemConfigApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(email="admin@example.com", password="pass", is_staff=True)
        self.user = User.objects.create_user(email="user@example.com", password="pass")

    def test_requires_admin(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get(reverse("system-config-list"))
        self.assertEqual(response.status_code, 403)

    def test_list_and_update(self):
        client = APIClient()
        client.force_authenticate(self.admin)

        listed = client.get(reverse("system-config-list"))
        self.assertEqual(listed.status_code, 200)
        keys = {row["key"] for row in listed.data}
        self.assertIn("events.retention_days", keys)

        updated = client.patch(
            reverse("system-config-detail", kwargs={"key": "events.retention_days"}),
            data={"value": 14},
            format="json",
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data["value"], 14)
        self.assertEqual(SystemConfig.objects.get(key="events.retention_days").value, 14)
