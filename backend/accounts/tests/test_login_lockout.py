from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import User


class LoginLockoutTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="lock@example.com", password="correct-horse")

    def tearDown(self):
        cache.clear()

    def _login(self, password: str):
        return self.client.post(
            reverse("auth-login"),
            data={"email": "lock@example.com", "password": password},
            format="json",
        )

    @override_settings(ACCOUNT_LOCKOUT_THRESHOLD=3, ACCOUNT_LOCKOUT_WINDOW_SECONDS=900)
    def test_account_locks_after_threshold(self):
        for _ in range(3):
            self.assertEqual(self._login("wrong").status_code, 401)

        # Locked now — even the correct password is refused with 429.
        resp = self._login("correct-horse")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["error"]["status"], "rate_limited")

        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.locked_until)

    @override_settings(ACCOUNT_LOCKOUT_THRESHOLD=3)
    def test_failed_attempts_increment_then_reset_on_success(self):
        self.assertEqual(self._login("wrong").status_code, 401)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)

        self.assertEqual(self._login("correct-horse").status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertIsNone(self.user.locked_until)

    @override_settings(ACCOUNT_LOCKOUT_THRESHOLD=3, ACCOUNT_LOCKOUT_WINDOW_SECONDS=900)
    def test_lock_expires_and_allows_login(self):
        for _ in range(3):
            self._login("wrong")
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.locked_until)

        # Simulate the lock window elapsing.
        User.objects.filter(pk=self.user.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
        resp = self._login("correct-horse")
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        self.assertEqual(self.user.failed_login_attempts, 0)

    @override_settings(ACCOUNT_LOCKOUT_THRESHOLD=0)
    def test_threshold_zero_disables_lockout(self):
        for _ in range(6):
            self.assertEqual(self._login("wrong").status_code, 401)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)


class LoginThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_login_is_rate_limited_by_ip(self):
        # DRF binds THROTTLE_RATES as a class attribute at import time, so patch the
        # shared rate dict directly (override_settings doesn't reach it). A
        # non-existent email avoids account-lockout interference, isolating the
        # per-IP ScopedRateThrottle.
        url = reverse("auth-login")
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"login": "3/min"}):
            for _ in range(3):
                resp = self.client.post(url, data={"email": "ghost@example.com", "password": "x"}, format="json")
                self.assertEqual(resp.status_code, 401)

            throttled = self.client.post(url, data={"email": "ghost@example.com", "password": "x"}, format="json")
            self.assertEqual(throttled.status_code, 429)
