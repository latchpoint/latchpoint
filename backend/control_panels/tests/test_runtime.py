"""Tests for control panel runtime wiring (`control_panels.runtime.initialize`)."""

from __future__ import annotations

import gc
from unittest.mock import MagicMock, patch

from django.test import TestCase

from alarm.signals import alarm_state_change_committed
from control_panels import runtime


class RuntimeInitializeTests(TestCase):
    def setUp(self):
        runtime._initialized = False

    def tearDown(self):
        alarm_state_change_committed.disconnect(dispatch_uid="control_panels_alarm_state_changed")
        runtime._initialized = False

    def test_state_change_receiver_survives_garbage_collection(self):
        # Regression (2026-10-23): the receiver is a closure local to `initialize()`. Connected
        # with the default weak ref it was collected on return, so no alarm state change ever
        # reached the keypad — a disarm never silenced the burglar siren.
        gateway = MagicMock()
        worker = MagicMock()
        with (
            patch("alarm.gateways.zwavejs.default_zwavejs_gateway", gateway),
            patch("control_panels.sync_worker.panel_sync_worker", worker),
        ):
            runtime.initialize()

        gc.collect()
        alarm_state_change_committed.send(sender=None, state_to="disarmed")

        worker.request_sync.assert_called_once_with()
