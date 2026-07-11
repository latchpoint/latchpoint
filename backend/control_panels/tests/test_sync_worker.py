"""Tests for the panel-sync worker (ADR-0100)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from control_panels.sync_worker import _SYNC_MAX_ATTEMPTS, PanelSyncWorker

_SYNC_FN = "control_panels.zwave_ring_keypad_v2.sync_ring_keypad_v2_devices_state"
_PLAY_FN = "control_panels.zwave_ring_keypad_v2.play_code_rejected"


class PanelSyncWorkerTests(TestCase):
    def setUp(self):
        self.worker = PanelSyncWorker()

    def test_burst_of_sync_requests_coalesces_to_one_reconcile(self):
        self.worker.request_sync()
        self.worker.request_sync()
        self.worker.request_sync()

        with patch(_SYNC_FN, return_value=0) as sync:
            self.worker._drain()

        sync.assert_called_once_with(force_siren_edge=False)

    def test_drain_without_work_is_a_no_op(self):
        with patch(_SYNC_FN, return_value=0) as sync:
            self.worker._drain()
        sync.assert_not_called()

    def test_siren_reassert_passes_force_edge(self):
        self.worker.request_siren_reassert()

        with patch(_SYNC_FN, return_value=0) as sync:
            self.worker._drain()

        sync.assert_called_once_with(force_siren_edge=True)

    def test_failed_sync_retries_up_to_max_attempts(self):
        self.worker.request_sync()

        with (
            patch(_SYNC_FN, side_effect=[1, 1, 0]) as sync,
            patch("control_panels.sync_worker.time.sleep") as sleep,
        ):
            self.worker._drain()

        self.assertEqual(sync.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_gives_up_after_max_attempts(self):
        self.worker.request_sync()

        with (
            patch(_SYNC_FN, return_value=1) as sync,
            patch("control_panels.sync_worker.time.sleep"),
        ):
            self.worker._drain()

        self.assertEqual(sync.call_count, _SYNC_MAX_ATTEMPTS)
        # The failure is not retried forever; the next request reconciles again.
        self.worker.request_sync()
        with patch(_SYNC_FN, return_value=0) as sync2:
            self.worker._drain()
        sync2.assert_called_once()

    def test_failed_sync_stops_retrying_when_newer_state_requested(self):
        self.worker.request_sync()

        def fail_and_request_newer(**_kwargs):
            if sync.call_count == 1:
                self.worker.request_sync()  # a newer transition landed mid-retry
                return 1
            return 0

        with (
            patch(_SYNC_FN, side_effect=fail_and_request_newer) as sync,
            patch("control_panels.sync_worker.time.sleep") as sleep,
        ):
            self.worker._drain()

        # No backoff sleep: the failed attempt is abandoned in favor of the newer state.
        self.assertEqual(sync.call_count, 2)
        sleep.assert_not_called()

    def test_code_rejected_one_shot_plays_on_drain(self):
        device = ControlPanelDevice.objects.create(
            name="Ring",
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            enabled=True,
            external_key="zwavejs:1:12",
            external_id={"home_id": 1, "node_id": 12},
        )
        self.worker.request_code_rejected(device_id=device.id)

        with patch(_PLAY_FN) as play:
            self.worker._drain()

        play.assert_called_once()
        self.assertEqual(play.call_args.kwargs["device"].id, device.id)

    def test_code_rejected_for_missing_device_is_ignored(self):
        self.worker.request_code_rejected(device_id=999999)
        with patch(_PLAY_FN) as play:
            self.worker._drain()
        play.assert_not_called()
