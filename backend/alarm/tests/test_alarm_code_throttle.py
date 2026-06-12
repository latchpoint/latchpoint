from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User, UserCode
from alarm.models import AlarmSettingsProfile, SystemConfig
from alarm.tests.settings_test_utils import set_profile_settings


def _set_config(key: str, value: int) -> None:
    SystemConfig.objects.update_or_create(
        key=key,
        defaults={"name": key, "value_type": "integer", "value": value},
    )


class AlarmCodeRateLimitAndLockoutTests(APITestCase):
    """Alarm arm/disarm rate limiting + lockout now flow through ``alarm.code_attempt_guard``.

    Both layers return HTTP 429 (``RateLimitedError``); a wrong code without throttling/lockout
    returns 401 (``InvalidCode``).
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="armer@example.com", password="pass")
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("1234"),
            label="Test Code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(profile, delay_time=5, arming_time=5, trigger_time=5, code_arm_required=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse("alarm-disarm")

    def tearDown(self):
        cache.clear()

    def test_disarm_is_rate_limited(self):
        _set_config("alarm_code.rate_limit_max_attempts", 3)
        _set_config("alarm_code.rate_limit_window_seconds", 60)
        _set_config("alarm_code.lockout_threshold", 0)  # isolate the rate-limit layer

        for _ in range(3):
            resp = self.client.post(self.url, data={"code": "9999"}, format="json")
            self.assertNotEqual(resp.status_code, 429)

        throttled = self.client.post(self.url, data={"code": "9999"}, format="json")
        self.assertEqual(throttled.status_code, 429)

    def test_lockout_blocks_after_threshold_even_with_correct_code(self):
        _set_config("alarm_code.rate_limit_max_attempts", 0)  # isolate the lockout layer
        _set_config("alarm_code.lockout_threshold", 3)
        _set_config("alarm_code.lockout_duration_seconds", 300)

        for _ in range(3):
            resp = self.client.post(self.url, data={"code": "9999"}, format="json")
            self.assertNotEqual(resp.status_code, 429)  # wrong code -> 401, not yet locked

        # Locked now: even the correct code is refused (mirrors login's pre-auth lock check).
        locked = self.client.post(self.url, data={"code": "1234"}, format="json")
        self.assertEqual(locked.status_code, 429)

    def test_no_block_when_both_disabled(self):
        _set_config("alarm_code.rate_limit_max_attempts", 0)
        _set_config("alarm_code.lockout_threshold", 0)

        for _ in range(15):
            resp = self.client.post(self.url, data={"code": "9999"}, format="json")
            self.assertNotEqual(resp.status_code, 429)
