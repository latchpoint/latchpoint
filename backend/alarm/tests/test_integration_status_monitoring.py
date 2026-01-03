"""Tests for integration status monitoring signals + persistence receivers."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from alarm import receivers, system_status
from alarm.models import AlarmEvent, AlarmEventType
from alarm.signals import integration_status_changed, integration_status_observed


class IntegrationStatusReceiversTests(TestCase):
    def setUp(self) -> None:
        receivers._offline_since.clear()
        receivers._offline_event_emitted.clear()

    def test_offline_threshold_emits_offline_event_once(self):
        base = timezone.now()

        with patch("alarm.receivers.timezone.now", return_value=base):
            integration_status_changed.send(
                sender=None,
                integration="mqtt",
                is_healthy=False,
                previous_healthy=True,
            )

        checked_at = base + timedelta(seconds=61)
        with patch("alarm.receivers.timezone.now", return_value=checked_at):
            integration_status_observed.send(
                sender=None,
                integration="mqtt",
                is_healthy=False,
                checked_at=checked_at,
            )

        self.assertEqual(
            AlarmEvent.objects.filter(event_type=AlarmEventType.INTEGRATION_OFFLINE).count(),
            1,
        )

        # Further observations should not emit duplicates.
        with patch("alarm.receivers.timezone.now", return_value=checked_at + timedelta(seconds=10)):
            integration_status_observed.send(
                sender=None,
                integration="mqtt",
                is_healthy=False,
                checked_at=checked_at + timedelta(seconds=10),
            )

        self.assertEqual(
            AlarmEvent.objects.filter(event_type=AlarmEventType.INTEGRATION_OFFLINE).count(),
            1,
        )

    def test_recovery_after_threshold_emits_recovered_event(self):
        base = timezone.now()

        with patch("alarm.receivers.timezone.now", return_value=base):
            integration_status_changed.send(
                sender=None,
                integration="mqtt",
                is_healthy=False,
                previous_healthy=True,
            )

        recovered_at = base + timedelta(seconds=61)
        with patch("alarm.receivers.timezone.now", return_value=recovered_at):
            integration_status_changed.send(
                sender=None,
                integration="mqtt",
                is_healthy=True,
                previous_healthy=False,
            )

        self.assertEqual(
            AlarmEvent.objects.filter(event_type=AlarmEventType.INTEGRATION_RECOVERED).count(),
            1,
        )
        event = AlarmEvent.objects.get(event_type=AlarmEventType.INTEGRATION_RECOVERED)
        self.assertEqual(event.metadata.get("integration"), "mqtt")
        self.assertGreaterEqual(float(event.metadata.get("offline_duration_seconds", 0)), 61.0)


class SystemStatusSignalEmissionTests(TestCase):
    def setUp(self) -> None:
        with system_status._status_lock:
            system_status._last_system_status_payload = None
            system_status._last_home_assistant_status = None
            system_status._last_integration_health.clear()

    def test_emits_observed_on_each_call_even_if_payload_unchanged(self):
        payload = {
            "home_assistant": {"configured": False, "reachable": False},
            "mqtt": {"connected": True},
            "zwavejs": {"connected": False},
            "zigbee2mqtt": {"enabled": False, "connected": False},
            "frigate": {"enabled": True, "available": True},
        }

        observed: list[dict] = []

        def _recv(sender, **kwargs) -> None:
            observed.append(kwargs)

        integration_status_observed.connect(_recv, dispatch_uid="test_observed", weak=False)
        self.addCleanup(lambda: integration_status_observed.disconnect(dispatch_uid="test_observed"))

        with patch("alarm.system_status._compute_system_status_payload", return_value=payload):
            system_status.recompute_and_broadcast_system_status(include_home_assistant=False)
            system_status.recompute_and_broadcast_system_status(include_home_assistant=False)

        # zigbee2mqtt and home_assistant are not configured/enabled in payload => ignored.
        self.assertEqual([o["integration"] for o in observed].count("mqtt"), 2)
        self.assertEqual([o["integration"] for o in observed].count("zwavejs"), 2)
        self.assertEqual([o["integration"] for o in observed].count("frigate"), 2)
        self.assertEqual([o["integration"] for o in observed].count("zigbee2mqtt"), 0)
        self.assertEqual([o["integration"] for o in observed].count("home_assistant"), 0)
