"""The siren re-assert from `manage.py run_task` stays out of the server's panel-sync worker's way (#164)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from alarm.models import AlarmState
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from control_panels.zwave_ring_keypad_v2 import _IND_BURGLAR_ALARM, reassert_ring_keypad_v2_siren_without_worker

_SET_VALUE = "alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"
_SNAPSHOT = "control_panels.zwave_ring_keypad_v2.get_current_snapshot"

# What the server's worker saves after it selects the disarmed mode indicator.
_WORKER_DISARMED = {"mode": 2, "state": AlarmState.DISARMED, "2:1": 99}


def _snapshot(state: str) -> SimpleNamespace:
    return SimpleNamespace(current_state=state, exit_at=None)


class ReassertSirenWithoutWorkerTests(TestCase):
    def setUp(self):
        self.device = ControlPanelDevice.objects.create(
            name="Ring",
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            enabled=True,
            external_key="zwavejs:4170970308:12",
            external_id={"home_id": 4170970308, "node_id": 12},
            beep_volume=77,
            last_written_indicators={},
        )

    def _written(self, set_value) -> list[tuple[int, int, object]]:
        return [(c.kwargs["property"], c.kwargs["property_key"], c.kwargs["value"]) for c in set_value.call_args_list]

    def test_sounds_the_siren_while_triggered(self):
        with patch(_SNAPSHOT, return_value=_snapshot(AlarmState.TRIGGERED)), patch(_SET_VALUE) as set_value:
            failed = reassert_ring_keypad_v2_siren_without_worker()

        self.assertEqual(failed, 0)
        written = self._written(set_value)
        # The siren write is last, nothing may follow it (ADR-0104).
        self.assertEqual(written[-1], (_IND_BURGLAR_ALARM, 7, 0))

    def test_stops_when_the_alarm_is_disarmed_mid_run(self):
        # Each write can take seconds. The user disarms after the first one, and the server's worker writes the
        # disarmed mode and saves it. The siren write must not follow, it would sound until the next disarm.
        states = iter([AlarmState.TRIGGERED, AlarmState.TRIGGERED, AlarmState.DISARMED])

        def snapshot(**_kwargs):
            return _snapshot(next(states, AlarmState.DISARMED))

        def disarm_after_first_write(**_kwargs):
            ControlPanelDevice.objects.filter(pk=self.device.pk).update(last_written_indicators=_WORKER_DISARMED)

        with patch(_SNAPSHOT, side_effect=snapshot), patch(_SET_VALUE, side_effect=disarm_after_first_write) as sv:
            reassert_ring_keypad_v2_siren_without_worker()

        written = self._written(sv)
        self.assertEqual(len(written), 1)
        self.assertNotIn((_IND_BURGLAR_ALARM, 7, 0), written)
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_written_indicators, _WORKER_DISARMED)

    def test_writes_nothing_once_the_alarm_is_disarmed(self):
        with patch(_SNAPSHOT, return_value=_snapshot(AlarmState.DISARMED)), patch(_SET_VALUE) as set_value:
            reassert_ring_keypad_v2_siren_without_worker()

        set_value.assert_not_called()

    def test_leaves_the_saved_device_state_to_the_worker(self):
        # The worker reconciles from its saved copy, so a run from another process doesn't overwrite it.
        with patch(_SNAPSHOT, return_value=_snapshot(AlarmState.TRIGGERED)), patch(_SET_VALUE):
            reassert_ring_keypad_v2_siren_without_worker()

        self.device.refresh_from_db()
        self.assertEqual(self.device.last_written_indicators, {})
        self.assertEqual(self.device.last_error, "")
