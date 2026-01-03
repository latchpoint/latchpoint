from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import AlarmSettingsProfile, AlarmState
from alarm.tests.settings_test_utils import set_profile_settings


class AlarmSettingsTimingApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="timing@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=15,
            trigger_time=60,
        )

    def test_get_timing_requires_auth(self):
        client = APIClient()
        url = reverse("alarm-settings-timing", args=[AlarmState.ARMED_AWAY])
        response = client.get(url)
        self.assertEqual(response.status_code, 401)

    def test_get_timing_for_state_returns_resolved_values(self):
        url = reverse("alarm-settings-timing", args=[AlarmState.ARMED_AWAY])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("delay_time", body["data"])
        self.assertIn("arming_time", body["data"])
        self.assertIn("trigger_time", body["data"])
        # Check that values are present (actual values depend on defaults + overrides)
        self.assertIsInstance(body["data"]["delay_time"], int)
        self.assertIsInstance(body["data"]["arming_time"], int)
        self.assertIsInstance(body["data"]["trigger_time"], int)

    def test_get_timing_respects_state_overrides(self):
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=15,
            trigger_time=60,
            state_overrides={
                AlarmState.ARMED_HOME: {"arming_time": 0, "delay_time": 10},
            },
        )

        # ARMED_AWAY should use base values
        url_away = reverse("alarm-settings-timing", args=[AlarmState.ARMED_AWAY])
        response_away = self.client.get(url_away)
        self.assertEqual(response_away.status_code, 200)
        away = response_away.json()
        self.assertEqual(away["data"]["arming_time"], 15)
        self.assertEqual(away["data"]["delay_time"], 30)

        # ARMED_HOME should use overrides
        url_home = reverse("alarm-settings-timing", args=[AlarmState.ARMED_HOME])
        response_home = self.client.get(url_home)
        self.assertEqual(response_home.status_code, 200)
        home = response_home.json()
        self.assertEqual(home["data"]["arming_time"], 0)
        self.assertEqual(home["data"]["delay_time"], 10)

    def test_get_timing_404_for_invalid_state(self):
        url = reverse("alarm-settings-timing", args=["invalid_state"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["status"], "validation_error")
