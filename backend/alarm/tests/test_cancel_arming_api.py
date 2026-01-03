from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState
from alarm.state_machine import transitions
from alarm.tests.settings_test_utils import set_profile_settings


class CancelArmingApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="cancel@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=30,
            trigger_time=30,
            code_arm_required=False,
        )

    def test_cancel_arming_requires_auth(self):
        client = APIClient()
        url = reverse("alarm-cancel-arming")
        response = client.post(url)
        self.assertEqual(response.status_code, 401)

    def test_cancel_arming_returns_disarmed_state(self):
        # Put alarm into arming state
        transitions.arm(target_state=AlarmState.ARMED_AWAY, user=self.user, reason="test")

        url = reverse("alarm-cancel-arming")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["current_state"], AlarmState.DISARMED)

    def test_cancel_arming_when_not_arming_returns_400(self):
        # Start from disarmed state
        transitions.disarm(reason="test_setup")

        url = reverse("alarm-cancel-arming")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["status"], "conflict")

    def test_cancel_arming_records_event(self):
        transitions.arm(target_state=AlarmState.ARMED_AWAY, user=self.user, reason="test")

        url = reverse("alarm-cancel-arming")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)

        # Should have recorded a disarmed event
        self.assertTrue(
            AlarmEvent.objects.filter(event_type=AlarmEventType.DISARMED).exists()
        )
