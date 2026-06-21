"""Tests for failure handling and circuit breaker."""

from datetime import timedelta
from unittest import TestCase
from unittest.mock import MagicMock

from django.utils import timezone

from alarm.dispatcher.failure_handler import (
    AUTO_RECOVERY_SECONDS,
    BACKOFF_SCHEDULE_SECONDS,
    CIRCUIT_BREAKER_THRESHOLD,
    clear_suspension,
    get_backoff_seconds,
    is_rule_allowed,
    record_rule_failure,
    record_rule_success,
)
from alarm.models import RuleRuntimeStatus


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


class TestStatusTracksSuspension(TestCase):
    """Regression: the `status` label must not get stuck at 'error_suspended' after recovery.

    The circuit breaker sets both `error_suspended=True` and `status='error_suspended'`, but the
    recovery paths previously cleared only the boolean — leaving an active rule falsely displaying
    'Error Suspended' (seen in prod on the alarm trigger rule).
    """

    def test_success_resets_stale_error_suspended_status(self):
        runtime = MagicMock()
        runtime.consecutive_failures = 4
        runtime.error_suspended = True
        runtime.status = "error_suspended"

        record_rule_success(runtime=runtime)

        self.assertFalse(runtime.error_suspended)
        self.assertEqual(runtime.status, RuleRuntimeStatus.PENDING)
        runtime.save.assert_called_once()
        self.assertIn("status", runtime.save.call_args.kwargs["update_fields"])

    def test_success_is_noop_when_nothing_to_clear(self):
        runtime = MagicMock()
        runtime.consecutive_failures = 0
        runtime.error_suspended = False

        record_rule_success(runtime=runtime)

        runtime.save.assert_not_called()

    def test_success_from_backoff_does_not_touch_a_non_suspended_status(self):
        runtime = MagicMock()
        runtime.consecutive_failures = 2  # backing off, but never circuit-broken
        runtime.error_suspended = False
        runtime.status = "pending"

        record_rule_success(runtime=runtime)

        runtime.save.assert_called_once()
        self.assertNotIn("status", runtime.save.call_args.kwargs["update_fields"])

    def test_clear_suspension_resets_stale_status(self):
        runtime = MagicMock()
        runtime.status = "error_suspended"

        clear_suspension(runtime=runtime)

        self.assertEqual(runtime.status, RuleRuntimeStatus.PENDING)
        self.assertIn("status", runtime.save.call_args.kwargs["update_fields"])

    def test_failure_at_threshold_sets_both_flag_and_status(self):
        rule = MagicMock(name="rule")
        rule.name = "trigger"
        rule.id = 3
        runtime = MagicMock()
        runtime.consecutive_failures = CIRCUIT_BREAKER_THRESHOLD - 1

        record_rule_failure(rule=rule, runtime=runtime, error="boom", now=timezone.now())

        self.assertTrue(runtime.error_suspended)
        self.assertEqual(runtime.status, "error_suspended")

    def test_failure_below_threshold_leaves_status_untouched(self):
        rule = MagicMock(name="rule")
        rule.name = "trigger"
        rule.id = 3
        runtime = MagicMock()
        runtime.consecutive_failures = 0
        runtime.status = "pending"

        record_rule_failure(rule=rule, runtime=runtime, error="boom", now=timezone.now())

        self.assertEqual(runtime.consecutive_failures, 1)
        self.assertEqual(runtime.status, "pending")
