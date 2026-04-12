from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User


class SettingsRegistryApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="registry@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_registry_requires_authentication(self):
        client = APIClient()
        response = client.get(reverse("alarm-settings-registry"))
        self.assertEqual(response.status_code, 401)

    def test_registry_returns_entries_with_expected_keys(self):
        response = self.client.get(reverse("alarm-settings-registry"))
        self.assertEqual(response.status_code, 200)

        entries = response.json()["data"]
        self.assertIsInstance(entries, list)
        self.assertGreater(len(entries), 0)

        required_keys = {"key", "name", "description", "config_schema", "encrypted_fields", "default"}
        for entry in entries:
            self.assertTrue(required_keys.issubset(entry.keys()), f"Missing keys in entry {entry.get('key')}")
            self.assertIsInstance(entry["config_schema"], dict)
            self.assertIn("properties", entry["config_schema"])
            self.assertIsInstance(entry["encrypted_fields"], list)
