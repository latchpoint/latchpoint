from __future__ import annotations

from unittest import mock

from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import User
from alarm.models import AlarmSettingsProfile
from alarm.tests.settings_test_utils import set_profile_settings


class AlarmCodeThrottleTests(APITestCase):
    """ArmAlarmView / DisarmAlarmView opt into the per-user ``alarm_code`` ScopedRateThrottle."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="armer@example.com", password="pass")
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(profile, delay_time=5, arming_time=5, trigger_time=5, code_arm_required=True)

    def tearDown(self):
        cache.clear()

    def test_disarm_is_rate_limited(self):
        # DRF binds THROTTLE_RATES as a class attribute at import time, and IS_TESTING disables
        # the `alarm_code` rate, so patch the shared dict directly (override_settings doesn't
        # reach it). Wrong-code disarms return a clean 401 until the throttle trips at 429.
        client = APIClient()
        client.force_authenticate(self.user)
        url = reverse("alarm-disarm")
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"alarm_code": "3/min"}):
            for _ in range(3):
                resp = client.post(url, data={"code": "9999"}, format="json")
                self.assertNotEqual(resp.status_code, 429)

            throttled = client.post(url, data={"code": "9999"}, format="json")
            self.assertEqual(throttled.status_code, 429)
