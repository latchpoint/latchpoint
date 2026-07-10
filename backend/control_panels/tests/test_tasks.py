"""Tests for the Ring Keypad v2 siren re-assert task (ADR-0098)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType, AlarmState
from control_panels.tasks import resync_ring_keypad_siren
from control_panels.zwave_ring_keypad_v2 import _BURGLAR_SIREN_MAX_TOTAL_SECONDS


def _snapshot(state: str) -> SimpleNamespace:
    return SimpleNamespace(current_state=state)


@patch("control_panels.tasks.panel_sync_worker")
@patch("control_panels.tasks.get_current_snapshot")
class ResyncRingKeypadSirenTests(TestCase):
    def test_resends_while_triggered(self, mock_snapshot, mock_worker):
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)
        AlarmEvent.objects.create(event_type=AlarmEventType.TRIGGERED, timestamp=timezone.now())

        result = resync_ring_keypad_siren()

        self.assertEqual(result, {"resynced": True})
        mock_worker.request_siren_reassert.assert_called_once()

    def test_noop_when_not_triggered(self, mock_snapshot, mock_worker):
        mock_snapshot.return_value = _snapshot(AlarmState.ARMED_AWAY)

        result = resync_ring_keypad_siren()

        self.assertEqual(result["reason"], "not_triggered")
        mock_worker.request_siren_reassert.assert_not_called()

    def test_noop_when_snapshot_missing(self, mock_snapshot, mock_worker):
        mock_snapshot.return_value = None

        result = resync_ring_keypad_siren()

        self.assertEqual(result["reason"], "not_triggered")
        mock_worker.request_siren_reassert.assert_not_called()

    def test_stops_after_bell_cutoff(self, mock_snapshot, mock_worker):
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)
        AlarmEvent.objects.create(
            event_type=AlarmEventType.TRIGGERED,
            timestamp=timezone.now() - timedelta(seconds=_BURGLAR_SIREN_MAX_TOTAL_SECONDS + 60),
        )

        result = resync_ring_keypad_siren()

        self.assertEqual(result["reason"], "bell_cutoff")
        mock_worker.request_siren_reassert.assert_not_called()

    def test_cutoff_measures_from_latest_trigger(self, mock_snapshot, mock_worker):
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)
        AlarmEvent.objects.create(
            event_type=AlarmEventType.TRIGGERED,
            timestamp=timezone.now() - timedelta(seconds=_BURGLAR_SIREN_MAX_TOTAL_SECONDS + 60),
        )
        AlarmEvent.objects.create(event_type=AlarmEventType.TRIGGERED, timestamp=timezone.now())

        result = resync_ring_keypad_siren()

        self.assertEqual(result, {"resynced": True})
        mock_worker.request_siren_reassert.assert_called_once()

    def test_resends_when_no_trigger_event_recorded(self, mock_snapshot, mock_worker):
        # Fail open: a triggered state with no recorded event should still sound the siren.
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)

        result = resync_ring_keypad_siren()

        self.assertEqual(result, {"resynced": True})
        mock_worker.request_siren_reassert.assert_called_once()
