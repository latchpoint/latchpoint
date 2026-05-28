"""Tests for the process_alarm_timers scheduled task.

These cover the *task wrapper* — the scheduled tick that advances exit_at-based
transitions without any client reading state. Per-branch transition correctness
already lives in test_transitions.py (via timer_expired directly).
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.models import AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Sensor
from alarm.state_machine.transitions import arm, sensor_triggered, timer_expired
from alarm.tasks import STUCK_TIMER_WARN_SECONDS, process_alarm_timers
from alarm.tests.settings_test_utils import set_profile_settings


class ProcessAlarmTimersTaskTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="task@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=10,
            trigger_time=20,
        )

    def _backdate_exit_at(self, seconds: int = 1) -> None:
        AlarmStateSnapshot.objects.update(exit_at=timezone.now() - timedelta(seconds=seconds))

    def test_advances_arming_to_armed_without_state_read(self):
        # The headline bug: arm, then never read state. The task alone must
        # advance arming -> armed_away.
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        self._backdate_exit_at()

        result = process_alarm_timers()

        self.assertEqual(result["processed"], True)
        self.assertEqual(result["state"], AlarmState.ARMED_AWAY)
        snapshot = AlarmStateSnapshot.objects.get()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)
        self.assertIsNone(snapshot.exit_at)

    def test_advances_pending_to_triggered_without_state_read(self):
        # Entry-delay (intruder) path has the same lazy gap: pending -> triggered.
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        self._backdate_exit_at()
        timer_expired()  # -> armed_away
        entry_sensor = Sensor.objects.create(name="Front Door", is_active=True, is_entry_point=True)
        sensor_triggered(sensor=entry_sensor)  # -> pending with exit_at
        self._backdate_exit_at()

        result = process_alarm_timers()

        self.assertEqual(result["state"], AlarmState.TRIGGERED)
        self.assertEqual(AlarmStateSnapshot.objects.get().current_state, AlarmState.TRIGGERED)

    def test_no_op_when_no_timer_due(self):
        # Fresh arming with a future exit_at must NOT be advanced early, and the
        # cheap pre-check should report nothing processed.
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)

        result = process_alarm_timers()

        self.assertEqual(result, {"processed": False})
        self.assertEqual(AlarmStateSnapshot.objects.get().current_state, AlarmState.ARMING)

    def test_no_op_when_disarmed(self):
        # Disarmed snapshot has exit_at=None -> pre-check filters it out.
        timer_expired()  # bootstrap a DISARMED snapshot

        result = process_alarm_timers()

        self.assertEqual(result, {"processed": False})

    def test_warns_when_timer_overdue_beyond_threshold(self):
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        self._backdate_exit_at(seconds=STUCK_TIMER_WARN_SECONDS + 5)

        with self.assertLogs("alarm.tasks", level="WARNING") as cm:
            result = process_alarm_timers()

        self.assertEqual(result["state"], AlarmState.ARMED_AWAY)
        self.assertTrue(any("overdue" in line for line in cm.output))

    def test_no_warning_for_fresh_overdue(self):
        # Within the warn threshold, no warning is logged.
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        self._backdate_exit_at(seconds=1)

        with self.assertNoLogs("alarm.tasks", level="WARNING"):
            process_alarm_timers()
