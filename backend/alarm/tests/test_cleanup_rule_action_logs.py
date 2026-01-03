"""Tests for rule action log cleanup task."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from alarm.models import RuleActionLog, RuleKind, SystemConfig
from alarm.tasks import cleanup_rule_action_logs, _get_rule_log_retention_days


class CleanupRuleActionLogsTests(TestCase):
    def test_deletes_logs_older_than_default_retention(self):
        """Logs older than 14 days (default) are deleted."""
        now = timezone.now()

        # Old log (should be deleted)
        RuleActionLog.objects.create(
            kind=RuleKind.TRIGGER,
            fired_at=now - timedelta(days=15),
        )
        # Recent log (should be kept)
        recent = RuleActionLog.objects.create(
            kind=RuleKind.TRIGGER,
            fired_at=now - timedelta(days=5),
        )

        deleted = cleanup_rule_action_logs()

        self.assertEqual(deleted, 1)
        self.assertEqual(RuleActionLog.objects.count(), 1)
        self.assertEqual(RuleActionLog.objects.first().pk, recent.pk)

    def test_respects_custom_retention_days(self):
        """Retention days can be configured via SystemConfig."""
        now = timezone.now()

        # Set retention to 7 days
        SystemConfig.objects.create(
            key="rule_logs.retention_days",
            name="Rule log retention (days)",
            value_type="integer",
            value=7,
        )

        # Log from 10 days ago (should be deleted with 7-day retention)
        RuleActionLog.objects.create(
            kind=RuleKind.TRIGGER,
            fired_at=now - timedelta(days=10),
        )
        # Log from 5 days ago (should be kept)
        recent = RuleActionLog.objects.create(
            kind=RuleKind.TRIGGER,
            fired_at=now - timedelta(days=5),
        )

        deleted = cleanup_rule_action_logs()

        self.assertEqual(deleted, 1)
        self.assertEqual(RuleActionLog.objects.count(), 1)
        self.assertEqual(RuleActionLog.objects.first().pk, recent.pk)

    def test_no_logs_to_delete(self):
        """Returns 0 when no logs are old enough."""
        now = timezone.now()

        RuleActionLog.objects.create(
            kind=RuleKind.TRIGGER,
            fired_at=now - timedelta(days=1),
        )

        deleted = cleanup_rule_action_logs()

        self.assertEqual(deleted, 0)
        self.assertEqual(RuleActionLog.objects.count(), 1)

    def test_deletes_multiple_old_logs(self):
        """Multiple old logs are deleted in one call."""
        now = timezone.now()

        for i in range(5):
            RuleActionLog.objects.create(
                kind=RuleKind.TRIGGER,
                fired_at=now - timedelta(days=20 + i),
            )

        deleted = cleanup_rule_action_logs()

        self.assertEqual(deleted, 5)
        self.assertEqual(RuleActionLog.objects.count(), 0)


class GetRuleLogRetentionDaysTests(TestCase):
    def test_returns_default_when_no_config(self):
        """Returns 14 (default) when no SystemConfig exists."""
        self.assertEqual(_get_rule_log_retention_days(), 14)

    def test_returns_configured_value(self):
        """Returns the configured value from SystemConfig."""
        SystemConfig.objects.create(
            key="rule_logs.retention_days",
            name="Rule log retention (days)",
            value_type="integer",
            value=7,
        )
        self.assertEqual(_get_rule_log_retention_days(), 7)

    def test_handles_invalid_value_gracefully(self):
        """Falls back to default on invalid config value."""
        SystemConfig.objects.create(
            key="rule_logs.retention_days",
            name="Rule log retention (days)",
            value_type="integer",
            value="not-a-number",
        )
        self.assertEqual(_get_rule_log_retention_days(), 14)
