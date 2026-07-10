from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from accounts.use_cases.user_codes import create_user_code
from alarm.models import AlarmSettingsProfile, AlarmState, Sensor
from alarm.state_machine.transitions import arm, disarm, get_current_snapshot, sensor_triggered, trigger
from alarm.tests.settings_test_utils import set_profile_settings
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from control_panels.sync_worker import panel_sync_worker
from control_panels.zwave_ring_keypad_v2 import (
    _BURGLAR_SIREN_SECONDS,
    handle_zwavejs_ring_keypad_v2_event,
    sync_ring_keypad_v2_devices_state,
)


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

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"),
        ):
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

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"),
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

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=4170970308),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value,
        ):
            handle_zwavejs_ring_keypad_v2_event(msg)
            # The feedback tone is queued on the panel-sync worker (ADR-0100), never written on
            # the inbound event thread; drain the worker to execute the queued write.
            panel_sync_worker._drain()

            # property=9 is "Code not accepted" for Ring Keypad v2.
            calls = [kwargs for _args, kwargs in set_value.call_args_list]
            self.assertTrue(any(call.get("property") == 9 for call in calls))
            self.assertTrue(
                any(
                    call.get("property") == 9 and call.get("property_key") == 9 and call.get("value") == 77
                    for call in calls
                )
            )

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
        self.assertTrue(
            any(
                call.get("property") == 18 and call.get("property_key") == 9 and call.get("value") == 77
                for call in calls
            )
        )

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
        self.assertTrue(
            any(
                call.get("property") == 17 and call.get("property_key") == 9 and call.get("value") == 77
                for call in calls
            )
        )

    def test_sync_triggered_sounds_sustained_burglar_siren(self):
        # Arm, then force TRIGGERED. The burglar siren must sound (non-zero Indicator CC timeout).
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        trigger(user=None, reason="test")

        snapshot = get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            sync_ring_keypad_v2_devices_state()

        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        # Burglar alarm indicator = property 13. The tone starts on any value-CHANGING write to the
        # Indicator CC timeout (property_key 7) — ADR-0100. With no tracked register value (fresh
        # device), the sync must write 0 then the duration: both orderings sound the siren no matter
        # what the physical register held (writing only the duration risks a same-value no-op = the
        # silent siren of ADR-0099).
        self.assertGreater(_BURGLAR_SIREN_SECONDS, 0)
        key7_values = [
            call.get("value") for call in calls if call.get("property") == 13 and call.get("property_key") == 7
        ]
        self.assertIn(0, key7_values, "unknown-register trigger must reset-then-set to guarantee a value change")
        self.assertIn(_BURGLAR_SIREN_SECONDS, key7_values)
        self.assertLess(
            key7_values.index(0),
            key7_values.index(_BURGLAR_SIREN_SECONDS),
            "burglar key 7 must go 0 -> duration (reset before activate)",
        )
        # The FINAL burglar key-7 write must be non-zero so the tone auto-stops after the duration.
        self.assertEqual(key7_values[-1], _BURGLAR_SIREN_SECONDS)
        # No multilevel/key 1 write — indicator 13 does not support it (it was silently ignored).
        self.assertFalse(any(call.get("property") == 13 and call.get("property_key") == 1 for call in calls))
        # Minutes timeout pinned to 0 so the play duration is exactly the seconds value.
        self.assertTrue(
            any(
                call.get("property") == 13 and call.get("property_key") == 6 and call.get("value") == 0
                for call in calls
            )
        )
        # Volume (key 9) set to the device's beep_volume.
        self.assertTrue(
            any(
                call.get("property") == 13 and call.get("property_key") == 9 and call.get("value") == 77
                for call in calls
            )
        )

    def test_sync_non_triggered_never_touches_burglar_timeout(self):
        # Regression guard for the 2026-07-10 arm-sounds-siren incident (ADR-0100): writing the
        # burglar timeout register OUTSIDE the triggered state activates the siren when the value
        # changes (the ADR-0099 "teardown clear" wrote 240 -> 0 on arming and sounded it). The
        # register must therefore never be written while the alarm is not triggered.
        self.device.last_written_indicators = {"13:7": _BURGLAR_SIREN_SECONDS, "state": "triggered"}
        self.device.save(update_fields=["last_written_indicators"])
        snapshot = get_current_snapshot(process_timers=False)
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            sync_ring_keypad_v2_devices_state()

        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        self.assertFalse(
            any(call.get("property") == 13 and call.get("property_key") == 7 for call in calls),
            "a non-triggered sync must never write the burglar timeout register",
        )
        # Leaving triggered still silences the tone by re-selecting the mode indicator.
        self.assertTrue(any(call.get("property") == 2 and call.get("property_key") == 1 for call in calls))

    def test_sync_second_trigger_uses_reset_then_set(self):
        # Every trigger sounds the siren via reset-then-set (0 then the duration): a 0-write is
        # hardware-verified to ALWAYS activate (even over an already-0 register) and 0 -> 240 is a
        # verified activator, so the sequence works regardless of what the register holds. No
        # single-write alternation: that would depend on unverified same-value/dedupe semantics.
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        trigger(user=None, reason="test")
        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"):
            sync_ring_keypad_v2_devices_state()

        disarm(user=self.user, code=None, reason="test")
        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"):
            sync_ring_keypad_v2_devices_state()

        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        trigger(user=None, reason="test")
        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            sync_ring_keypad_v2_devices_state()

        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        key7_values = [
            call.get("value") for call in calls if call.get("property") == 13 and call.get("property_key") == 7
        ]
        self.assertEqual(
            key7_values,
            [0, _BURGLAR_SIREN_SECONDS],
            "every trigger must re-activate the siren via reset-then-set",
        )

    def test_sync_same_state_twice_is_a_no_op(self):
        # Diff-only reconciliation: once a state is fully synced, re-syncing the same state must
        # not issue any Z-Wave writes (no redundant supervised round-trips).
        arm(target_state=AlarmState.ARMED_HOME, user=None, code=None, reason="test")
        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as first:
            sync_ring_keypad_v2_devices_state()
        self.assertTrue(first.call_args_list)

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as second:
            sync_ring_keypad_v2_devices_state()
        self.assertEqual(second.call_args_list, [])

    def test_sync_records_tracked_registers(self):
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        trigger(user=None, reason="test")
        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"):
            sync_ring_keypad_v2_devices_state()

        self.device.refresh_from_db()
        tracked = self.device.last_written_indicators
        self.assertEqual(tracked.get("13:7"), _BURGLAR_SIREN_SECONDS)
        self.assertEqual(tracked.get("13:9"), 77)
        self.assertEqual(tracked.get("13:6"), 0)
        self.assertEqual(tracked.get("state"), "triggered")

    def test_failed_write_keeps_state_unsynced_for_retry(self):
        # A failed write must not advance the tracked state, so the next sync retries the writes.
        with patch(
            "alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value",
            side_effect=RuntimeError("zwave unreachable"),
        ):
            failed = sync_ring_keypad_v2_devices_state()
        self.assertEqual(failed, 1)
        self.device.refresh_from_db()
        self.assertTrue(self.device.last_error)
        self.assertNotEqual(self.device.last_written_indicators.get("state"), "disarmed")

        with patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value:
            failed = sync_ring_keypad_v2_devices_state()
        self.assertEqual(failed, 0)
        calls = [kwargs for _args, kwargs in set_value.call_args_list]
        self.assertTrue(any(call.get("property") == 2 and call.get("property_key") == 1 for call in calls))
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_written_indicators.get("state"), "disarmed")
        self.assertEqual(self.device.last_error, "")
