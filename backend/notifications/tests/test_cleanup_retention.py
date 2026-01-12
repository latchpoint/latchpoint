"""Tests for notification retention cleanup tasks."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmSettingsProfile, SystemConfig
from notifications.models import NotificationDelivery, NotificationLog
from notifications.tasks import cleanup_notification_deliveries, cleanup_notification_logs


class CleanupNotificationLogsTests(TestCase):
    def test_disabled_retention_does_not_delete(self):
        now = timezone.now()
        SystemConfig.objects.create(
            key="notification_logs.retention_days",
            name="Notification log retention (days)",
            value_type="integer",
            value=0,
        )
        log = NotificationLog.objects.create(
            provider=None,
            provider_name="PB",
            provider_type="pushbullet",
            status=NotificationLog.Status.SUCCESS,
            message_preview="hi",
            error_message="",
            error_code="",
            rule_name="",
        )
        NotificationLog.objects.filter(pk=log.pk).update(created_at=now - timedelta(days=100))

        deleted = cleanup_notification_logs()

        self.assertEqual(deleted, 0)
        self.assertEqual(NotificationLog.objects.count(), 1)

    def test_deletes_logs_older_than_retention_and_keeps_boundary(self):
        fixed_now = timezone.now()
        SystemConfig.objects.create(
            key="notification_logs.retention_days",
            name="Notification log retention (days)",
            value_type="integer",
            value=30,
        )

        old = NotificationLog.objects.create(
            provider=None,
            provider_name="PB",
            provider_type="pushbullet",
            status=NotificationLog.Status.SUCCESS,
            message_preview="old",
            error_message="",
            error_code="",
            rule_name="",
        )
        boundary = NotificationLog.objects.create(
            provider=None,
            provider_name="PB",
            provider_type="pushbullet",
            status=NotificationLog.Status.SUCCESS,
            message_preview="boundary",
            error_message="",
            error_code="",
            rule_name="",
        )
        recent = NotificationLog.objects.create(
            provider=None,
            provider_name="PB",
            provider_type="pushbullet",
            status=NotificationLog.Status.SUCCESS,
            message_preview="recent",
            error_message="",
            error_code="",
            rule_name="",
        )

        cutoff = fixed_now - timedelta(days=30)
        NotificationLog.objects.filter(pk=old.pk).update(created_at=cutoff - timedelta(seconds=1))
        NotificationLog.objects.filter(pk=boundary.pk).update(created_at=cutoff)
        NotificationLog.objects.filter(pk=recent.pk).update(created_at=cutoff + timedelta(seconds=1))

        with patch("notifications.tasks.timezone.now", return_value=fixed_now):
            deleted = cleanup_notification_logs()

        self.assertEqual(deleted, 1)
        self.assertEqual(NotificationLog.objects.count(), 2)
        self.assertTrue(NotificationLog.objects.filter(pk=boundary.pk).exists())
        self.assertTrue(NotificationLog.objects.filter(pk=recent.pk).exists())


class CleanupNotificationDeliveriesTests(TestCase):
    def setUp(self) -> None:
        self.profile = AlarmSettingsProfile.objects.create(name="default", is_active=True)

    def test_disabled_retention_does_not_delete(self):
        now = timezone.now()
        SystemConfig.objects.create(
            key="notification_deliveries.retention_days",
            name="Notification delivery retention (days)",
            value_type="integer",
            value=0,
        )
        delivery = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=None,
            provider_key="ha-system-provider",
            message="hello",
            title="",
            data={},
            rule_name="",
            status=NotificationDelivery.Status.SENT,
        )
        NotificationDelivery.objects.filter(pk=delivery.pk).update(created_at=now - timedelta(days=100))

        deleted = cleanup_notification_deliveries()

        self.assertEqual(deleted, 0)
        self.assertEqual(NotificationDelivery.objects.count(), 1)

    def test_deletes_only_sent_and_dead_older_than_retention(self):
        fixed_now = timezone.now()
        SystemConfig.objects.create(
            key="notification_deliveries.retention_days",
            name="Notification delivery retention (days)",
            value_type="integer",
            value=30,
        )

        sent_old = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=None,
            provider_key="ha-system-provider",
            message="sent old",
            title="",
            data={},
            rule_name="",
            status=NotificationDelivery.Status.SENT,
        )
        dead_old = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=None,
            provider_key="ha-system-provider",
            message="dead old",
            title="",
            data={},
            rule_name="",
            status=NotificationDelivery.Status.DEAD,
        )
        pending_old = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=None,
            provider_key="ha-system-provider",
            message="pending old",
            title="",
            data={},
            rule_name="",
            status=NotificationDelivery.Status.PENDING,
        )
        sending_old = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=None,
            provider_key="ha-system-provider",
            message="sending old",
            title="",
            data={},
            rule_name="",
            status=NotificationDelivery.Status.SENDING,
        )
        sent_boundary = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=None,
            provider_key="ha-system-provider",
            message="sent boundary",
            title="",
            data={},
            rule_name="",
            status=NotificationDelivery.Status.SENT,
        )
        dead_recent = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=None,
            provider_key="ha-system-provider",
            message="dead recent",
            title="",
            data={},
            rule_name="",
            status=NotificationDelivery.Status.DEAD,
        )

        cutoff = fixed_now - timedelta(days=30)
        NotificationDelivery.objects.filter(pk=sent_old.pk).update(created_at=cutoff - timedelta(seconds=1))
        NotificationDelivery.objects.filter(pk=dead_old.pk).update(created_at=cutoff - timedelta(seconds=1))
        NotificationDelivery.objects.filter(pk=pending_old.pk).update(created_at=cutoff - timedelta(seconds=1))
        NotificationDelivery.objects.filter(pk=sending_old.pk).update(created_at=cutoff - timedelta(seconds=1))
        NotificationDelivery.objects.filter(pk=sent_boundary.pk).update(created_at=cutoff)
        NotificationDelivery.objects.filter(pk=dead_recent.pk).update(created_at=cutoff + timedelta(seconds=1))

        with patch("notifications.tasks.timezone.now", return_value=fixed_now):
            deleted = cleanup_notification_deliveries()

        self.assertEqual(deleted, 2)
        remaining = NotificationDelivery.objects.values_list("pk", flat=True)
        self.assertIn(pending_old.pk, remaining)
        self.assertIn(sending_old.pk, remaining)
        self.assertIn(sent_boundary.pk, remaining)
        self.assertIn(dead_recent.pk, remaining)
        self.assertNotIn(sent_old.pk, remaining)
        self.assertNotIn(dead_old.pk, remaining)

