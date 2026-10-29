"""Tests for the Ring Keypad v2 siren watchdog task (ADR-0104)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmEvent, AlarmEventType, AlarmState
from control_panels.sync_worker import PanelSyncWorker
from control_panels.tasks import resync_ring_keypad_siren


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

    def test_no_bell_cutoff_however_long_the_alarm_has_been_triggered(self, mock_snapshot, mock_worker):
        # ADR-0104 removed the ADR-0098 bell cutoff: the siren has no device-side auto-stop, so
        # declining to re-assert would no longer silence anything — it would just stop repairing
        # a siren that is meant to sound until someone disarms.
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)
        AlarmEvent.objects.create(
            event_type=AlarmEventType.TRIGGERED,
            timestamp=timezone.now() - timedelta(hours=6),
        )

        result = resync_ring_keypad_siren()

        self.assertEqual(result, {"resynced": True})
        mock_worker.request_siren_reassert.assert_called_once()

    def test_resends_when_no_trigger_event_recorded(self, mock_snapshot, mock_worker):
        # A triggered state with no recorded event should still sound the siren.
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)

        result = resync_ring_keypad_siren()

        self.assertEqual(result, {"resynced": True})
        mock_worker.request_siren_reassert.assert_called_once()


@patch("control_panels.tasks.get_current_snapshot")
class ResyncRingKeypadSirenOutsideTheServerTests(TestCase):
    """`manage.py run_task` has no panel-sync worker thread, so the task writes the siren itself (#164)."""

    def test_writes_the_siren_when_no_worker_is_running(self, mock_snapshot):
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)
        worker = PanelSyncWorker()

        with (
            patch("control_panels.tasks.panel_sync_worker", worker),
            patch(
                "control_panels.zwave_ring_keypad_v2.reassert_ring_keypad_v2_siren_without_worker", return_value=0
            ) as reassert,
            patch.object(worker, "request_siren_reassert") as request,
        ):
            result = resync_ring_keypad_siren()

        self.assertEqual(result, {"resynced": True, "failed_devices": 0})
        reassert.assert_called_once_with()
        request.assert_not_called()

    def test_leaves_it_to_the_worker_in_the_server(self, mock_snapshot):
        mock_snapshot.return_value = _snapshot(AlarmState.TRIGGERED)
        worker = PanelSyncWorker()

        with (
            patch("control_panels.tasks.panel_sync_worker", worker),
            patch.object(worker, "is_running", return_value=True),
            patch.object(worker, "request_siren_reassert") as request,
            patch("control_panels.zwave_ring_keypad_v2.reassert_ring_keypad_v2_siren_without_worker") as reassert,
        ):
            result = resync_ring_keypad_siren()

        self.assertEqual(result, {"resynced": True})
        request.assert_called_once_with()
        reassert.assert_not_called()
