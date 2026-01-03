from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User


class DefaultAuthRequiredApiTests(APITestCase):
    def test_rules_requires_auth(self):
        url = reverse("alarm-rules")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_sensors_requires_auth(self):
        url = reverse("alarm-sensors")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_rules_allows_authenticated(self):
        user = User.objects.create_user(email="authz@example.com", password="pass")
        self.client.force_authenticate(user)
        url = reverse("alarm-rules")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

