"""Tests for the rules-engine repositories adapter, focused on get_alarm_state.

Regression guard: rule evaluation must see the true alarm state, including the
transient `arming`/`pending` windows. A prior `exit_at__isnull=True` filter
returned None whenever a timer was pending, which (combined with a stuck timer)
left armed-state-gated intrusion rules unable to match.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.models import AlarmSettingsProfile, AlarmState, AlarmStateSnapshot
from alarm.rules.repositories import default_rule_engine_repositories
from alarm.state_machine.transitions import arm, timer_expired
from alarm.tests.settings_test_utils import set_profile_settings


class GetAlarmStateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="repo@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, arming_time=30, delay_time=30, trigger_time=20)

    def _get_alarm_state(self):
        return default_rule_engine_repositories().get_alarm_state()

    def test_returns_none_when_no_snapshot(self):
        self.assertIsNone(self._get_alarm_state())

    def test_returns_arming_while_timer_pending(self):
        # The key regression: a pending exit_at must NOT mask the real state.
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        self.assertEqual(AlarmStateSnapshot.objects.get().current_state, AlarmState.ARMING)
        self.assertEqual(self._get_alarm_state(), AlarmState.ARMING)

    def test_returns_armed_state_after_timer_clears(self):
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        AlarmStateSnapshot.objects.update(exit_at=timezone.now() - timedelta(seconds=1))
        timer_expired()
        self.assertEqual(self._get_alarm_state(), AlarmState.ARMED_AWAY)
