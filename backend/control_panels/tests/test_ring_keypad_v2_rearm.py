from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from accounts.models import User
from accounts.use_cases.user_codes import create_user_code
from alarm import rearm_guard
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState
from alarm.state_machine.transitions import arm, get_current_snapshot
from alarm.tests.settings_test_utils import set_profile_settings
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from control_panels.zwave_ring_keypad_v2 import handle_zwavejs_ring_keypad_v2_event

_HOME_ID = 4170970308
_NODE_ID = 12


def _arm_away_event() -> dict:
    return {
        "type": "event",
        "event": {
            "source": "node",
            "nodeId": _NODE_ID,
            "args": {"commandClass": 111, "eventType": 5, "eventData": "1996"},
        },
    }


def _disarm_event() -> dict:
    return {
        "type": "event",
        "event": {
            "source": "node",
            "nodeId": _NODE_ID,
            "args": {"commandClass": 111, "eventType": 3, "eventData": "1996"},
        },
    }


class RingKeypadV2RearmGuardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="test@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, delay_time=30, arming_time=0, trigger_time=20, code_arm_required=True)
        self.code = create_user_code(user=self.user, raw_code="1996")
        self.device = ControlPanelDevice.objects.create(
            name="Ring",
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            enabled=True,
            external_key=f"zwavejs:{_HOME_ID}:{_NODE_ID}",
            external_id={"home_id": _HOME_ID, "node_id": _NODE_ID},
            beep_volume=77,
        )

    def test_arm_blocked_within_rearm_window(self):
        """A keypad arm landing inside the post-disarm window is refused, not executed."""
        rearm_guard.mark_disarmed()  # simulate a disarm that just committed

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=_HOME_ID),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value") as set_value,
        ):
            handle_zwavejs_ring_keypad_v2_event(_arm_away_event())

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.DISARMED)
        failed = list(AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE))
        self.assertTrue(any(e.metadata.get("reason") == "rearm_guard" for e in failed))
        # "Code not accepted" indicator (property 9) is signaled.
        calls = [kwargs for _a, kwargs in set_value.call_args_list]
        self.assertTrue(any(c.get("property") == 9 for c in calls))

    def test_arm_allowed_when_not_recently_disarmed(self):
        """Sanity: with no recent disarm, a valid keypad arm still arms."""
        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=_HOME_ID),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"),
        ):
            handle_zwavejs_ring_keypad_v2_event(_arm_away_event())

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.ARMED_AWAY)


class RingKeypadV2ValidationErrorTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="test@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, delay_time=30, arming_time=0, trigger_time=20, code_arm_required=True)
        self.code = create_user_code(user=self.user, raw_code="1996")
        self.device = ControlPanelDevice.objects.create(
            name="Ring",
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            enabled=True,
            external_key=f"zwavejs:{_HOME_ID}:{_NODE_ID}",
            external_id={"home_id": _HOME_ID, "node_id": _NODE_ID},
            beep_volume=77,
        )

    def test_unexpected_validation_error_is_not_recorded_as_failed_code(self):
        """A non-CodeValidationError (e.g. DB fault) must not be logged as a wrong-code attempt."""
        arm(target_state=AlarmState.ARMED_HOME, user=None, code=None, reason="test")

        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=_HOME_ID),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"),
            patch(
                "accounts.use_cases.code_validation.validate_any_active_code",
                side_effect=RuntimeError("db down"),
            ),
        ):
            handle_zwavejs_ring_keypad_v2_event(_disarm_event())

        # Disarm did not happen (error), and it was NOT recorded as a failed code.
        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.ARMED_HOME)
        self.assertFalse(AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE).exists())

    def test_invalid_code_is_recorded_as_failed_code(self):
        """A genuine wrong code still records a failed_code attempt (unchanged behavior)."""
        bad = {
            "type": "event",
            "event": {
                "source": "node",
                "nodeId": _NODE_ID,
                "args": {"commandClass": 111, "eventType": 3, "eventData": "0000"},
            },
        }
        with (
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.get_home_id", return_value=_HOME_ID),
            patch("alarm.gateways.zwavejs.DefaultZwavejsGateway.set_value"),
        ):
            handle_zwavejs_ring_keypad_v2_event(bad)

        self.assertTrue(AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE).exists())
