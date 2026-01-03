from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, User, UserRoleAssignment, UserTOTPDevice
from accounts.serializers import UserSerializer


class TestUserSerializerPrefetch(TestCase):
    def test_prefetched_user_serialization_runs_without_queries(self):
        user = User.objects.create_user(email="prefetched@example.com", password="pass")
        role, _created = Role.objects.get_or_create(
            slug="resident", defaults={"name": "Resident"}
        )
        UserRoleAssignment.objects.create(user=user, role=role)
        UserTOTPDevice.objects.create(
            user=user,
            label="phone",
            secret_encrypted=b"secret",
            is_active=True,
            confirmed_at=timezone.now(),
        )

        prefetched = (
            User.objects.filter(id=user.id)
            .prefetch_related("role_assignments__role", "totp_devices")
            .get()
        )
        with self.assertNumQueries(0):
            data = UserSerializer(prefetched).data

        self.assertEqual(data["role"], "resident")
        self.assertTrue(data["has2FA"])
