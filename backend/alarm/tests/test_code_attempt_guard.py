from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from alarm import code_attempt_guard
from alarm.models import AlarmCodeLockout, SystemConfig


def _set_config(key: str, value: int) -> None:
    SystemConfig.objects.update_or_create(
        key=key,
        defaults={"name": key, "value_type": "integer", "value": value},
    )


class CodeAttemptGuardRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_allows_up_to_max_then_blocks(self):
        _set_config("alarm_code.rate_limit_max_attempts", 3)
        _set_config("alarm_code.rate_limit_window_seconds", 60)
        for _ in range(3):
            self.assertTrue(code_attempt_guard.check_rate_limit("web:user:1"))
        self.assertFalse(code_attempt_guard.check_rate_limit("web:user:1"))

    def test_separate_source_keys_have_separate_budgets(self):
        _set_config("alarm_code.rate_limit_max_attempts", 1)
        self.assertTrue(code_attempt_guard.check_rate_limit("a"))
        self.assertFalse(code_attempt_guard.check_rate_limit("a"))
        # A different source still has its own budget.
        self.assertTrue(code_attempt_guard.check_rate_limit("b"))

    def test_disabled_when_max_is_zero(self):
        _set_config("alarm_code.rate_limit_max_attempts", 0)
        for _ in range(50):
            self.assertTrue(code_attempt_guard.check_rate_limit("web:user:1"))

    def test_fails_open_when_cache_unavailable(self):
        _set_config("alarm_code.rate_limit_max_attempts", 1)
        with mock.patch.object(code_attempt_guard, "cache") as mock_cache:
            mock_cache.add.side_effect = RuntimeError("cache down")
            self.assertTrue(code_attempt_guard.check_rate_limit("web:user:1"))
            self.assertTrue(code_attempt_guard.check_rate_limit("web:user:1"))

    def test_uses_registry_default_when_no_config_row(self):
        # Default max is 10; the 11th attempt in the window is blocked.
        for _ in range(10):
            self.assertTrue(code_attempt_guard.check_rate_limit("web:user:1"))
        self.assertFalse(code_attempt_guard.check_rate_limit("web:user:1"))


class CodeAttemptGuardLockoutTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_locks_after_threshold_and_reports_remaining(self):
        _set_config("alarm_code.lockout_threshold", 3)
        _set_config("alarm_code.lockout_duration_seconds", 300)

        self.assertEqual(code_attempt_guard.is_locked_out(), (False, 0))
        for _ in range(2):
            code_attempt_guard.register_failed_attempt()
        self.assertFalse(code_attempt_guard.is_locked_out()[0])

        code_attempt_guard.register_failed_attempt()  # third failure trips the lock
        locked, remaining = code_attempt_guard.is_locked_out()
        self.assertTrue(locked)
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 300)

        # Counter is reset when the lock engages (fresh budget after cooldown).
        row = AlarmCodeLockout.objects.get(id=AlarmCodeLockout.SINGLETON_ID)
        self.assertEqual(row.failed_attempts, 0)

    def test_reset_clears_counter_and_lock(self):
        _set_config("alarm_code.lockout_threshold", 2)
        _set_config("alarm_code.lockout_duration_seconds", 300)
        code_attempt_guard.register_failed_attempt()
        code_attempt_guard.register_failed_attempt()  # locks
        self.assertTrue(code_attempt_guard.is_locked_out()[0])

        code_attempt_guard.reset_lockout()
        self.assertFalse(code_attempt_guard.is_locked_out()[0])
        row = AlarmCodeLockout.objects.get(id=AlarmCodeLockout.SINGLETON_ID)
        self.assertEqual(row.failed_attempts, 0)
        self.assertIsNone(row.locked_until)

    def test_disabled_when_threshold_is_zero(self):
        _set_config("alarm_code.lockout_threshold", 0)
        for _ in range(20):
            code_attempt_guard.register_failed_attempt()
        self.assertFalse(code_attempt_guard.is_locked_out()[0])
        # Disabled lockout never even creates the row.
        self.assertFalse(AlarmCodeLockout.objects.exists())

    def test_expired_lock_reads_as_unlocked(self):
        _set_config("alarm_code.lockout_threshold", 1)
        _set_config("alarm_code.lockout_duration_seconds", 300)
        code_attempt_guard.register_failed_attempt()  # locks immediately
        self.assertTrue(code_attempt_guard.is_locked_out()[0])

        AlarmCodeLockout.objects.filter(id=AlarmCodeLockout.SINGLETON_ID).update(
            locked_until=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(code_attempt_guard.is_locked_out(), (False, 0))

    def test_uses_registry_default_threshold_when_no_config_row(self):
        # Default threshold is 5: four failures do not lock, the fifth does.
        for _ in range(4):
            code_attempt_guard.register_failed_attempt()
        self.assertFalse(code_attempt_guard.is_locked_out()[0])
        code_attempt_guard.register_failed_attempt()
        self.assertTrue(code_attempt_guard.is_locked_out()[0])
