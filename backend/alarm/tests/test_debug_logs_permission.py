from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import Role, User, UserRoleAssignment


class DebugLogsPermissionTests(APITestCase):
    """The HTTP debug-logs view must use the project-wide ``is_admin`` predicate (IsAdminRole),
    matching the WebSocket log-stream gating in AlarmConsumer — not is_staff-only IsAdminUser."""

    def _client(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_role_admin_without_staff_can_read_logs(self):
        user = User.objects.create_user(email="roleadmin@example.com", password="pass")
        role, _ = Role.objects.get_or_create(slug="admin", defaults={"name": "Admin"})
        UserRoleAssignment.objects.create(user=user, role=role)

        resp = self._client(user).get(reverse("debug-logs"))
        self.assertEqual(resp.status_code, 200)

    def test_regular_member_is_forbidden(self):
        member = User.objects.create_user(email="member@example.com", password="pass")
        resp = self._client(member).get(reverse("debug-logs"))
        self.assertEqual(resp.status_code, 403)

    def test_staff_can_read_logs(self):
        staff = User.objects.create_user(email="staff@example.com", password="pass", is_staff=True)
        resp = self._client(staff).get(reverse("debug-logs"))
        self.assertEqual(resp.status_code, 200)
