from __future__ import annotations

import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from accounts.models import User
from accounts.use_cases.user_codes import create_user_code
from alarm import rearm_guard
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState
from alarm.state_machine.transitions import arm, get_current_snapshot
from alarm.tests.settings_test_utils import set_profile_setting, set_profile_settings
from integrations_home_assistant.mqtt_alarm_entity import COMMAND_TOPIC, handle_mqtt_alarm_command


def _cmd(action: str, code: str | None = "1996") -> str:
    return json.dumps({"action": action, "code": code or ""})


class MqttAlarmCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="test@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, delay_time=30, arming_time=0, trigger_time=20, code_arm_required=True)
        # The MQTT alarm entity handler is gated on this profile setting being enabled.
        set_profile_setting(self.profile, "home_assistant_alarm_entity", {"enabled": True})
        self.code = create_user_code(user=self.user, raw_code="1996")

    def _send(self, action: str, code: str | None = "1996") -> None:
        handle_mqtt_alarm_command(topic=COMMAND_TOPIC, payload=_cmd(action, code))

    def test_rearm_guard_blocks_arm_after_disarm(self):
        """An ARM command landing inside the post-disarm window is refused (reproduces the incident)."""
        rearm_guard.mark_disarmed()  # simulate a disarm that just committed

        self._send("ARM_AWAY")

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.DISARMED)
        failed = list(AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE))
        self.assertTrue(any(e.metadata.get("reason") == "rearm_guard" for e in failed))

    def test_arm_allowed_when_not_recently_disarmed(self):
        """Sanity: with no recent disarm, a valid arm command still arms."""
        self._send("ARM_AWAY")
        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.ARMED_AWAY)

    def test_duplicate_disarm_commands_are_collapsed(self):
        """Three identical DISARMs in a burst disarm once and record a single code_used."""
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")

        self._send("DISARM")
        self._send("DISARM")
        self._send("DISARM")

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.DISARMED)
        self.assertEqual(AlarmEvent.objects.filter(event_type=AlarmEventType.CODE_USED).count(), 1)

    def test_corrected_retry_with_different_code_is_not_deduped(self):
        """A fast retry with a *different* code has a different fingerprint and is processed."""
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")

        self._send("DISARM", code="0000")  # wrong code -> failed
        self._send("DISARM", code="1996")  # correct code -> must NOT be swallowed

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.DISARMED)

    def test_unexpected_validation_error_is_not_recorded_as_failed_code(self):
        """A non-CodeValidationError must be logged, not counted as a wrong-code attempt."""
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")

        with patch(
            "accounts.use_cases.code_validation.validate_any_active_code",
            side_effect=RuntimeError("db down"),
        ):
            self._send("DISARM")

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.ARMED_AWAY)
        self.assertFalse(AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE).exists())

    def test_invalid_code_is_recorded_as_failed_code(self):
        """A genuine wrong code still records a failed_code attempt (unchanged behavior)."""
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")

        self._send("DISARM", code="0000")

        self.assertEqual(get_current_snapshot(process_timers=False).current_state, AlarmState.ARMED_AWAY)
        self.assertTrue(AlarmEvent.objects.filter(event_type=AlarmEventType.FAILED_CODE).exists())
