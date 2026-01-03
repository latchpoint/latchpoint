from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User


class UsersApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="user@example.com", password="pass")
        self.admin = User.objects.create_superuser(email="admin@example.com", password="pass")
        self.other_user = User.objects.create_user(email="other@example.com", password="pass")

    def test_list_users_requires_auth(self):
        client = APIClient()
        url = reverse("users")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_list_users_returns_all_users(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        url = reverse("users")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body["data"], list)
        self.assertGreaterEqual(len(body["data"]), 3)

    def test_current_user_requires_auth(self):
        client = APIClient()
        url = reverse("users-me")
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_current_user_returns_authenticated_user(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("users-me")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["email"], "user@example.com")

    def test_current_user_includes_id(self):
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("users-me")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("id", body["data"])
        self.assertEqual(str(body["data"]["id"]), str(self.user.id))
