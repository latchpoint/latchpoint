from __future__ import annotations

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import Role, User, UserRoleAssignment
from alarm.models import AlarmSettingsProfile, AlarmStateSnapshot


class OnboardingApiTests(APITestCase):
    def setUp(self):
        self.url = reverse("onboarding")

    def test_onboarding_creates_admin_user(self):
        payload = {
            "email": "admin@example.com",
            "password": "StrongPass123!",
        }
        response = self.client.post(self.url, data=payload)
        self.assertEqual(response.status_code, 201)

        user = User.objects.get(email="admin@example.com")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.timezone, settings.TIME_ZONE)

        role = Role.objects.get(slug="admin")
        self.assertTrue(
            UserRoleAssignment.objects.filter(user=user, role=role).exists()
        )
        self.assertFalse(AlarmSettingsProfile.objects.filter(is_active=True).exists())
        self.assertFalse(AlarmStateSnapshot.objects.exists())

    def test_onboarding_blocks_when_user_exists(self):
        User.objects.create_user(email="existing@example.com", password="pass")
        response = self.client.post(
            self.url,
            data={
                "email": "admin2@example.com",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_status_when_onboarding_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["onboarding_required"])

    def test_status_when_onboarding_completed(self):
        User.objects.create_user(email="existing@example.com", password="pass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["onboarding_required"])

    @override_settings(TIME_ZONE="America/New_York")
    def test_onboarding_uses_timezone_from_settings(self):
        response = self.client.post(
            self.url,
            data={
                "email": "admin3@example.com",
                "password": "StrongPass123!",
            },
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="admin3@example.com")
        self.assertEqual(user.timezone, "America/New_York")
