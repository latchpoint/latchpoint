"""Tests for the alarm-triggered notification receiver (ADR-0098)."""

from __future__ import annotations

from django.test import TestCase

from alarm.models import AlarmSettingsProfile, AlarmState
from alarm.signals import alarm_state_change_committed
from notifications.models import NotificationDelivery, NotificationProvider


class NotifyOnAlarmTriggeredTests(TestCase):
    def setUp(self) -> None:
        self.profile = AlarmSettingsProfile.objects.create(name="default", is_active=True)
        self.enabled_provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.fake"},
            is_enabled=True,
        )
        self.disabled_provider = NotificationProvider.objects.create(
            profile=self.profile,
            name="Discord (off)",
            provider_type="discord",
            config={"webhook_url": "https://example.com/hook"},
            is_enabled=False,
        )

    def test_enqueues_to_enabled_providers_on_triggered(self):
        alarm_state_change_committed.send(sender=None, state_to=AlarmState.TRIGGERED)

        deliveries = NotificationDelivery.objects.all()
        self.assertEqual(deliveries.count(), 1)
        delivery = deliveries.get()
        self.assertEqual(delivery.provider_id, self.enabled_provider.id)
        self.assertEqual(delivery.title, "Alarm triggered")
        self.assertIn("TRIGGERED", delivery.message)
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)

    def test_ignores_other_transitions(self):
        for state in (AlarmState.DISARMED, AlarmState.ARMED_AWAY, AlarmState.PENDING):
            alarm_state_change_committed.send(sender=None, state_to=state)

        self.assertEqual(NotificationDelivery.objects.count(), 0)

    def test_no_providers_is_a_noop(self):
        NotificationProvider.objects.all().delete()

        alarm_state_change_committed.send(sender=None, state_to=AlarmState.TRIGGERED)

        self.assertEqual(NotificationDelivery.objects.count(), 0)

    def test_ignores_providers_from_other_profiles(self):
        other_profile = AlarmSettingsProfile.objects.create(name="other", is_active=False)
        NotificationProvider.objects.create(
            profile=other_profile,
            name="Other PB",
            provider_type="pushbullet",
            config={"access_token": "enc:o.other"},
            is_enabled=True,
        )

        alarm_state_change_committed.send(sender=None, state_to=AlarmState.TRIGGERED)

        deliveries = NotificationDelivery.objects.all()
        self.assertEqual(deliveries.count(), 1)
        self.assertEqual(deliveries.get().provider_id, self.enabled_provider.id)
