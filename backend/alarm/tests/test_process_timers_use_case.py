from __future__ import annotations

from django.test import TestCase

from alarm.models import AlarmSettingsProfile, AlarmState
from alarm.use_cases.process_timers import tick_alarm_timers


class ProcessTimersUseCaseTests(TestCase):
    def test_tick_returns_state(self):
        AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        result = tick_alarm_timers()
        self.assertEqual(result.state, AlarmState.DISARMED)

