from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment


class TestUsersListQueries(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin-queries@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_users_list_is_constant_queries(self):
        user = User.objects.create_user(email="user-queries@example.com", password="pass")
        role, _created = Role.objects.get_or_create(slug="resident", defaults={"name": "Resident"})
        UserRoleAssignment.objects.create(user=user, role=role)

        url = reverse("users")
        with self.assertNumQueries(4):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

