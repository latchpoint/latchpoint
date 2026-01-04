"""Tests for failure handling and circuit breaker."""

from datetime import timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.utils import timezone

from alarm.dispatcher.failure_handler import (
    AUTO_RECOVERY_SECONDS,
    BACKOFF_SCHEDULE_SECONDS,
    CIRCUIT_BREAKER_THRESHOLD,
    get_backoff_seconds,
    is_rule_allowed,
)


class TestGetBackoffSeconds(TestCase):
    """Tests for get_backoff_seconds function."""

    def test_zero_failures_returns_zero(self):
        """Zero or negative failures return 0."""
        self.assertEqual(get_backoff_seconds(0), 0)
        self.assertEqual(get_backoff_seconds(-1), 0)

    def test_first_failure_returns_first_backoff(self):
        """First failure returns first backoff value."""
        self.assertEqual(get_backoff_seconds(1), BACKOFF_SCHEDULE_SECONDS[0])

    def test_increasing_failures_increase_backoff(self):
        """Backoff increases with failure count."""
        for i, expected in enumerate(BACKOFF_SCHEDULE_SECONDS, 1):
            self.assertEqual(get_backoff_seconds(i), expected)

    def test_high_failure_count_caps_at_max(self):
        """Backoff caps at the maximum value."""
        max_backoff = BACKOFF_SCHEDULE_SECONDS[-1]
        self.assertEqual(get_backoff_seconds(100), max_backoff)
        self.assertEqual(get_backoff_seconds(1000), max_backoff)


class TestIsRuleAllowed(TestCase):
    """Tests for is_rule_allowed function."""

    def test_allowed_when_no_restrictions(self):
        """Rule is allowed when not suspended and no backoff."""
        runtime = MagicMock()
        runtime.error_suspended = False
        runtime.next_allowed_at = None

        allowed, reason = is_rule_allowed(runtime=runtime, now=timezone.now())
        self.assertTrue(allowed)
        self.assertEqual(reason, "allowed")

    def test_not_allowed_when_suspended(self):
        """Rule is not allowed when suspended (before recovery time)."""
        runtime = MagicMock()
        runtime.error_suspended = True
        runtime.next_allowed_at = timezone.now() + timedelta(hours=1)

        allowed, reason = is_rule_allowed(runtime=runtime, now=timezone.now())
        self.assertFalse(allowed)
        self.assertEqual(reason, "suspended")

    def test_allowed_for_auto_recovery(self):
        """Suspended rule is allowed after recovery time passes."""
        runtime = MagicMock()
        runtime.error_suspended = True
        runtime.next_allowed_at = timezone.now() - timedelta(seconds=1)

        allowed, reason = is_rule_allowed(runtime=runtime, now=timezone.now())
        self.assertTrue(allowed)
        self.assertEqual(reason, "auto_recovery")

    def test_not_allowed_during_backoff(self):
        """Rule is not allowed during backoff period."""
        runtime = MagicMock()
        runtime.error_suspended = False
        runtime.next_allowed_at = timezone.now() + timedelta(seconds=30)

        allowed, reason = is_rule_allowed(runtime=runtime, now=timezone.now())
        self.assertFalse(allowed)
        self.assertIn("backoff", reason)

    def test_allowed_after_backoff_expires(self):
        """Rule is allowed after backoff period expires."""
        runtime = MagicMock()
        runtime.error_suspended = False
        runtime.next_allowed_at = timezone.now() - timedelta(seconds=1)

        allowed, reason = is_rule_allowed(runtime=runtime, now=timezone.now())
        self.assertTrue(allowed)
        self.assertEqual(reason, "allowed")


class TestConstants(TestCase):
    """Tests for module constants."""

    def test_backoff_schedule_is_increasing(self):
        """Backoff schedule values are increasing."""
        for i in range(1, len(BACKOFF_SCHEDULE_SECONDS)):
            self.assertGreater(
                BACKOFF_SCHEDULE_SECONDS[i],
                BACKOFF_SCHEDULE_SECONDS[i - 1],
            )

    def test_circuit_breaker_threshold_is_reasonable(self):
        """Circuit breaker threshold is a reasonable value."""
        self.assertGreater(CIRCUIT_BREAKER_THRESHOLD, 0)
        self.assertLess(CIRCUIT_BREAKER_THRESHOLD, 100)

    def test_auto_recovery_seconds_is_at_least_an_hour(self):
        """Auto recovery period is at least an hour."""
        self.assertGreaterEqual(AUTO_RECOVERY_SECONDS, 3600)
