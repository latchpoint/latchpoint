from __future__ import annotations

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment, UserTOTPDevice


class TestCurrentUserQueries(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="me-queries@example.com", password="pass")
        role, _created = Role.objects.get_or_create(slug="resident", defaults={"name": "Resident"})
        UserRoleAssignment.objects.create(user=self.user, role=role)
        UserTOTPDevice.objects.create(
            user=self.user,
            label="phone",
            secret_encrypted=b"secret",
            is_active=True,
            confirmed_at=timezone.now(),
        )

        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_current_user_is_constant_queries(self):
        url = reverse("users-me")
        with self.assertNumQueries(4):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["data"]["role"], "resident")
        self.assertTrue(body["data"]["has2FA"])
