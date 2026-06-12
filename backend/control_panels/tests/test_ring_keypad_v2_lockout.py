from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from accounts.models import User
from accounts.use_cases.user_codes import create_user_code
from alarm.models import AlarmCodeLockout, AlarmSettingsProfile, AlarmState
from alarm.state_machine.transitions import arm, get_current_snapshot
from alarm.tests.settings_test_utils import set_profile_settings
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from control_panels.zwave_ring_keypad_v2 import handle_zwavejs_ring_keypad_v2_event


def _set_config(key: str, value: int) -> None:
    from alarm.models import SystemConfig

    SystemConfig.objects.update_or_create(
        key=key,
        defaults={"name": key, "value_type": "integer", "value": value},
    )


def _disarm_event(code: str) -> dict:
    return {
        "type": "event",
        "event": {
            "source": "node",
            "nodeId": 12,
            "args": {"commandClass": 111, "eventType": 3, "eventData": code},
        },
    }


class RingKeypadV2LockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="kp@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=0,
            trigger_time=20,
            code_arm_required=True,
            state_overrides={},
        )
        self.code = create_user_code(user=self.user, raw_code="1996")
        self.device = ControlPanelDevice.objects.create(
            name="Ring",
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            enabled=True,
            external_key="zwavejs:4170970308:12",
            external_id={"home_id": 4170970308, "node_id": 12},
            beep_volume=77,
            action_map={"disarm": "disarmed", "arm_home": "armed_home", "arm_away": "armed_away"},
        )
        # Isolate the lockout layer from the rate limiter.
        _set_config("alarm_code.rate_limit_max_attempts", 0)
        _set_config("alarm_code.lockout_threshold", 2)
        _set_config("alarm_code.lockout_duration_seconds", 300)

    def tearDown(self):
        cache.clear()

    def test_lockout_refuses_valid_code_at_keypad(self):
        arm(target_state=AlarmState.ARMED_HOME, user=None, code=None, reason="test")

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"),
        ):
            # Two wrong codes engage the global lockout (threshold=2).
            handle_zwavejs_ring_keypad_v2_event(_disarm_event("0000"))
            handle_zwavejs_ring_keypad_v2_event(_disarm_event("0000"))

        self.assertTrue(AlarmCodeLockout.objects.get(id=AlarmCodeLockout.SINGLETON_ID).locked_until is not None)
        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.ARMED_HOME)

        # A correct code while locked is refused: state stays armed, "code not accepted" indicator fires.
        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value,
        ):
            handle_zwavejs_ring_keypad_v2_event(_disarm_event("1996"))

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.ARMED_HOME)
        properties = [kwargs.get("property") for _args, kwargs in set_value.call_args_list]
        self.assertIn(9, properties)  # 9 == "Code not accepted"

    def test_valid_code_resets_counter(self):
        arm(target_state=AlarmState.ARMED_HOME, user=None, code=None, reason="test")

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"),
        ):
            handle_zwavejs_ring_keypad_v2_event(_disarm_event("0000"))  # one failure (threshold=2)
            handle_zwavejs_ring_keypad_v2_event(_disarm_event("1996"))  # valid -> disarms + resets

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.DISARMED)
        row = AlarmCodeLockout.objects.filter(id=AlarmCodeLockout.SINGLETON_ID).first()
        # Reset clears the counter; no active lockout.
        self.assertTrue(row is None or (row.failed_attempts == 0 and row.locked_until is None))
