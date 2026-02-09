from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from accounts.use_cases.user_codes import create_user_code
from alarm.models import AlarmSettingsProfile, AlarmState
from alarm.tests.settings_test_utils import set_profile_settings
from alarm.models import Sensor
from alarm.state_machine.transitions import arm, get_current_snapshot, sensor_triggered
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from control_panels.zwave_ring_keypad_v2 import handle_zwavejs_ring_keypad_v2_event, sync_ring_keypad_v2_devices_state


class RingKeypadV2ControlPanelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="pass")
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
            action_map={
                "disarm": "disarmed",
                "arm_home": "armed_home",
                "arm_away": "armed_away",
                "cancel": "cancel_arming",
            },
        )

    def test_arm_away_with_valid_code_arms(self):
        msg = {
            "type": "event",
            "event": {
                "source": "node",
                "nodeId": 12,
                "args": {"commandClass": 111, "eventType": 5, "eventData": "1996"},
            },
        }

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308), patch(
            "alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"
        ) as set_value:
            handle_zwavejs_ring_keypad_v2_event(msg)

            snapshot = get_current_snapshot(process_timers=False)
            self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)
            # Indicator sync is handled via `alarm_state_change_committed` in runtime (not invoked here).

    def test_disarm_via_entry_control_notification_event_shape(self):
        # Start armed.
        arm(target_state=AlarmState.ARMED_HOME, user=None, code=None, reason="test")

        msg = {
            "type": "event",
            "event": {
                "source": "node",
                "event": "notification",
                "nodeId": 12,
                "endpointIndex": 0,
                "ccId": 111,
                "args": {"eventType": 2, "eventData": "1996"},
            },
        }

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308), patch(
            "alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"
        ):
            handle_zwavejs_ring_keypad_v2_event(msg)

        snapshot = get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

    def test_disarm_with_invalid_code_plays_error_indicator(self):
        msg = {
            "type": "event",
            "event": {
                "source": "node",
                "nodeId": 12,
                "args": {"commandClass": 111, "eventType": 3, "eventData": "0000"},
            },
        }

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308), patch(
            "alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"
        ) as set_value:
            handle_zwavejs_ring_keypad_v2_event(msg)

            # property=9 is "Code not accepted" for Ring Keypad v2.
            calls = [kwargs for _args, kwargs in set_value.call_args_list]
            self.assertTrue(any(call.get("property") == 9 for call in calls))
            self.assertTrue(any(call.get("property") == 9 and call.get("property_key") == 9 and call.get("value") == 77 for call in calls))

    def test_sync_maps_armed_night_to_armed_home_indicator(self):
        arm(target_state=AlarmState.ARMED_NIGHT, user=None, code=None, reason="test")

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            sync_ring_keypad_v2_devices_state()

        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        self.assertTrue(any(call.get("property") == 10 and call.get("property_key") == 1 for call in calls))

    def test_sync_maps_armed_vacation_to_armed_away_indicator(self):
        arm(target_state=AlarmState.ARMED_VACATION, user=None, code=None, reason="test")

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            sync_ring_keypad_v2_devices_state()

        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        self.assertTrue(any(call.get("property") == 11 and call.get("property_key") == 1 for call in calls))

    def test_sync_arming_sets_exit_delay_indicator(self):
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=15,
            trigger_time=20,
            code_arm_required=True,
            state_overrides={},
        )

        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        snapshot = get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            sync_ring_keypad_v2_devices_state()

        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        self.assertTrue(any(call.get("property") == 18 and call.get("property_key") == 7 for call in calls))
        self.assertTrue(any(call.get("property") == 18 and call.get("property_key") == 9 and call.get("value") == 77 for call in calls))

    def test_sync_pending_sets_entry_delay_indicator(self):
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        sensor = Sensor.objects.create(name="Door", is_entry_point=True)
        sensor_triggered(sensor=sensor, user=None, reason="test")

        snapshot = get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            sync_ring_keypad_v2_devices_state()

        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        self.assertTrue(any(call.get("property") == 17 and call.get("property_key") == 7 for call in calls))
        self.assertTrue(any(call.get("property") == 17 and call.get("property_key") == 9 and call.get("value") == 77 for call in calls))
