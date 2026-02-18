"""
Tests for notification outbox deliveries.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmSettingsProfile
from notifications.dispatcher import HA_SYSTEM_PROVIDER_ID, get_dispatcher
from notifications.handlers.base import NotificationResult
from notifications.models import NotificationDelivery, NotificationProvider
from notifications.tasks import notifications_send_pending


class TestNotificationOutbox(TestCase):
    def setUp(self) -> None:
        self.profile = AlarmSettingsProfile.objects.create(name="default", is_active=True)

    def test_enqueue_creates_delivery(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.fake"},
            is_enabled=True,
        )
        dispatcher = get_dispatcher()
        delivery, result = dispatcher.enqueue(
            profile=self.profile,
            provider_id=str(provider.id),
            message="Hello",
            title="Title",
            data={"url": "https://example.com"},
            rule_name="Rule",
        )
        self.assertTrue(result.success)
        self.assertIsNotNone(delivery)
        assert delivery is not None
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)
        self.assertEqual(delivery.provider_key, str(provider.id))

    def test_enqueue_ha_system_requires_service(self):
        dispatcher = get_dispatcher()
        delivery, result = dispatcher.enqueue(
            profile=self.profile,
            provider_id=HA_SYSTEM_PROVIDER_ID,
            message="Hello",
            data={},
            rule_name="Rule",
        )
        self.assertFalse(result.success)
        self.assertIsNone(delivery)
        self.assertEqual(result.error_code, "MISSING_SERVICE")

    def test_task_sends_pending_delivery_success(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.fake"},
            is_enabled=True,
        )
        delivery = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=provider,
            provider_key=str(provider.id),
            message="Hello",
            title="",
            data={},
            rule_name="Rule",
            status=NotificationDelivery.Status.PENDING,
            next_attempt_at=timezone.now(),
            max_attempts=2,
        )

        with patch("notifications.tasks.get_dispatcher") as mocked_get_dispatcher:
            mocked_get_dispatcher.return_value._send_now.return_value = NotificationResult.ok("sent")
            sent = notifications_send_pending()

        self.assertEqual(sent, 1)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.Status.SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertIsNotNone(delivery.sent_at)

    def test_task_retries_transient_failure(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.fake"},
            is_enabled=True,
        )
        delivery = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=provider,
            provider_key=str(provider.id),
            message="Hello",
            title="",
            data={},
            rule_name="Rule",
            status=NotificationDelivery.Status.PENDING,
            next_attempt_at=timezone.now(),
            max_attempts=3,
        )

        with patch("notifications.tasks.get_dispatcher") as mocked_get_dispatcher:
            mocked_get_dispatcher.return_value._send_now.return_value = NotificationResult.error(
                "timeout",
                code="TIMEOUT",
            )
            notifications_send_pending()

        delivery.refresh_from_db()
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)
        self.assertEqual(delivery.last_error_code, "TIMEOUT")
        self.assertGreater(delivery.next_attempt_at, timezone.now())

    def test_task_marks_delivery_dead_on_non_retryable_error(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.fake"},
            is_enabled=True,
        )
        delivery = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=provider,
            provider_key=str(provider.id),
            message="Hello",
            title="",
            data={},
            rule_name="Rule",
            status=NotificationDelivery.Status.PENDING,
            next_attempt_at=timezone.now(),
            max_attempts=5,
        )

        with patch("notifications.tasks.get_dispatcher") as mocked_get_dispatcher:
            mocked_get_dispatcher.return_value._send_now.return_value = NotificationResult.error(
                "auth failed",
                code="AUTH_FAILED",
            )
            notifications_send_pending()

        delivery.refresh_from_db()
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.status, NotificationDelivery.Status.DEAD)
        self.assertEqual(delivery.last_error_code, "AUTH_FAILED")

    def test_task_marks_delivery_dead_when_max_attempts_reached(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.fake"},
            is_enabled=True,
        )
        delivery = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=provider,
            provider_key=str(provider.id),
            message="Hello",
            title="",
            data={},
            rule_name="Rule",
            status=NotificationDelivery.Status.PENDING,
            attempt_count=1,
            next_attempt_at=timezone.now(),
            max_attempts=2,
        )

        with patch("notifications.tasks.get_dispatcher") as mocked_get_dispatcher:
            mocked_get_dispatcher.return_value._send_now.return_value = NotificationResult.error(
                "timeout",
                code="TIMEOUT",
            )
            notifications_send_pending()

        delivery.refresh_from_db()
        self.assertEqual(delivery.attempt_count, 2)
        self.assertEqual(delivery.status, NotificationDelivery.Status.DEAD)
        self.assertEqual(delivery.last_error_code, "TIMEOUT")

    def test_task_applies_rate_limited_backoff_window(self):
        provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.fake"},
            is_enabled=True,
        )
        delivery = NotificationDelivery.objects.create(
            profile=self.profile,
            provider=provider,
            provider_key=str(provider.id),
            message="Hello",
            title="",
            data={},
            rule_name="Rule",
            status=NotificationDelivery.Status.PENDING,
            next_attempt_at=timezone.now(),
            max_attempts=4,
        )
        started_at = timezone.now()

        with (
            patch("notifications.tasks.get_dispatcher") as mocked_get_dispatcher,
            patch("notifications.tasks.random.uniform", return_value=0.0),
        ):
            mocked_get_dispatcher.return_value._send_now.return_value = NotificationResult.error(
                "rate limited",
                code="RATE_LIMITED",
            )
            notifications_send_pending()

        delivery.refresh_from_db()
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)
        self.assertEqual(delivery.last_error_code, "RATE_LIMITED")

        delay = delivery.next_attempt_at - started_at
        self.assertGreaterEqual(delay, timedelta(seconds=30))
        self.assertLess(delay, timedelta(seconds=35))
