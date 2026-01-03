from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User, UserCode
from alarm.models import AlarmStateSnapshot


class SetupStatusApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="setup@example.com", password="pass")
        self.client.force_authenticate(self.user)

    def test_setup_not_required_when_no_codes(self):
        url = reverse("onboarding-setup-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["data"]["setup_required"])
        self.assertFalse(body["data"]["requirements"]["has_alarm_code"])

    def test_setup_not_required_when_code_exists(self):
        UserCode.objects.create(
            user=self.user,
            code_hash="not-used-here",
            label="Test",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        url = reverse("onboarding-setup-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["data"]["setup_required"])
        self.assertTrue(body["data"]["requirements"]["has_alarm_code"])

    def test_setup_status_bootstraps_snapshot_if_missing(self):
        AlarmStateSnapshot.objects.all().delete()
        url = reverse("onboarding-setup-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["data"]["setup_required"])
        self.assertTrue(body["data"]["requirements"]["has_alarm_snapshot"])
