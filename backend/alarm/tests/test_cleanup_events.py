"""Tests for event cleanup task."""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType, SystemConfig
from alarm.tasks import cleanup_old_events, _get_retention_days


class CleanupOldEventsTests(TestCase):
    def test_disabled_retention_does_not_delete(self):
        """Retention <= 0 disables cleanup to avoid deleting all rows."""
        now = timezone.now()

        SystemConfig.objects.create(
            key="events.retention_days",
            name="Event retention (days)",
            value_type="integer",
            value=0,
        )

        old = AlarmEvent.objects.create(
            event_type=AlarmEventType.DISARMED,
            timestamp=now - timedelta(days=365),
        )

        deleted = cleanup_old_events()

        self.assertEqual(deleted, 0)
        self.assertTrue(AlarmEvent.objects.filter(pk=old.pk).exists())

    def test_deletes_events_older_than_default_retention(self):
        """Events older than 30 days (default) are deleted."""
        now = timezone.now()

        # Old event (should be deleted)
        AlarmEvent.objects.create(
            event_type=AlarmEventType.DISARMED,
            timestamp=now - timedelta(days=31),
        )
        # Recent event (should be kept)
        recent = AlarmEvent.objects.create(
            event_type=AlarmEventType.ARMED,
            timestamp=now - timedelta(days=5),
        )

        deleted = cleanup_old_events()

        self.assertEqual(deleted, 1)
        self.assertEqual(AlarmEvent.objects.count(), 1)
        self.assertEqual(AlarmEvent.objects.first().pk, recent.pk)

    def test_respects_custom_retention_days(self):
        """Retention days can be configured via SystemConfig."""
        now = timezone.now()

        # Set retention to 7 days
        SystemConfig.objects.create(
            key="events.retention_days",
            name="Event retention (days)",
            value_type="integer",
            value=7,
        )

        # Event from 10 days ago (should be deleted with 7-day retention)
        AlarmEvent.objects.create(
            event_type=AlarmEventType.DISARMED,
            timestamp=now - timedelta(days=10),
        )
        # Event from 5 days ago (should be kept)
        recent = AlarmEvent.objects.create(
            event_type=AlarmEventType.ARMED,
            timestamp=now - timedelta(days=5),
        )

        deleted = cleanup_old_events()

        self.assertEqual(deleted, 1)
        self.assertEqual(AlarmEvent.objects.count(), 1)
        self.assertEqual(AlarmEvent.objects.first().pk, recent.pk)

    def test_no_events_to_delete(self):
        """Returns 0 when no events are old enough."""
        now = timezone.now()

        AlarmEvent.objects.create(
            event_type=AlarmEventType.ARMED,
            timestamp=now - timedelta(days=1),
        )

        deleted = cleanup_old_events()

        self.assertEqual(deleted, 0)
        self.assertEqual(AlarmEvent.objects.count(), 1)

    def test_deletes_multiple_old_events(self):
        """Multiple old events are deleted in one call."""
        now = timezone.now()

        for i in range(5):
            AlarmEvent.objects.create(
                event_type=AlarmEventType.DISARMED,
                timestamp=now - timedelta(days=40 + i),
            )

        deleted = cleanup_old_events()

        self.assertEqual(deleted, 5)
        self.assertEqual(AlarmEvent.objects.count(), 0)


class GetRetentionDaysTests(TestCase):
    def test_returns_default_when_no_config(self):
        """Returns 30 (default) when no SystemConfig exists."""
        self.assertEqual(_get_retention_days(), 30)

    def test_returns_configured_value(self):
        """Returns the configured value from SystemConfig."""
        SystemConfig.objects.create(
            key="events.retention_days",
            name="Event retention (days)",
            value_type="integer",
            value=14,
        )
        self.assertEqual(_get_retention_days(), 14)

    def test_handles_invalid_value_gracefully(self):
        """Falls back to default on invalid config value."""
        SystemConfig.objects.create(
            key="events.retention_days",
            name="Event retention (days)",
            value_type="integer",
            value="not-a-number",
        )
        self.assertEqual(_get_retention_days(), 30)


class CleanupEventsCommandTests(TestCase):
    def test_management_command_runs(self):
        """The cleanup_events management command runs successfully."""
        now = timezone.now()
        AlarmEvent.objects.create(
            event_type=AlarmEventType.DISARMED,
            timestamp=now - timedelta(days=31),
        )

        out = StringIO()
        call_command("cleanup_events", stdout=out)

        self.assertIn("Deleted 1 old events", out.getvalue())
        self.assertEqual(AlarmEvent.objects.count(), 0)
