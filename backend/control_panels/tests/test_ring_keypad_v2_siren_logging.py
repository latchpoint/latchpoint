from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from alarm.models import AlarmSettingsProfile, AlarmState
from alarm.state_machine.transitions import arm, trigger
from alarm.tests.settings_test_utils import set_profile_settings
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from control_panels.zwave_ring_keypad_v2 import sync_ring_keypad_v2_devices_state

_LOGGER = "control_panels.zwave_ring_keypad_v2"
_BURGLAR_INDICATOR = 13  # _IND_BURGLAR_ALARM


class RingKeypadV2SirenLoggingTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, delay_time=30, arming_time=0, trigger_time=0)
        self.device = ControlPanelDevice.objects.create(
            name="Ring",
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            enabled=True,
            external_key="zwavejs:4170970308:13",
            external_id={"home_id": 4170970308, "node_id": 13},
            beep_volume=50,
        )

    def _to_triggered(self):
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        trigger(user=None, reason="test")

    def test_siren_command_is_logged_and_targets_burglar_indicator(self):
        """On trigger, the siren attempt is logged (INFO) and the burglar indicator is written."""
        self._to_triggered()

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value,
            self.assertLogs(_LOGGER, level="INFO") as cm,
        ):
            sync_ring_keypad_v2_devices_state()

        self.assertIn("burglar siren commanded", "\n".join(cm.output))
        properties = [kwargs.get("property") for _args, kwargs in set_value.call_args_list]
        self.assertIn(_BURGLAR_INDICATOR, properties)

    def test_failed_siren_write_logs_warning_instead_of_silent_swallow(self):
        """A failed siren write is logged (not silently swallowed) and never crashes the sync."""
        self._to_triggered()

        with (
            patch(
                "alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value",
                side_effect=RuntimeError("zwave unreachable"),
            ),
            self.assertLogs(_LOGGER, level="INFO") as cm,
        ):
            sync_ring_keypad_v2_devices_state()  # must not raise

        output = "\n".join(cm.output)
        self.assertIn("burglar siren commanded", output)  # attempt is visible
        self.assertIn("indicator write failed", output)  # failure is logged, not swallowed
