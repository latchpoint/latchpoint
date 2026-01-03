from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmSettingsProfile, AlarmState, AlarmStateSnapshot
from alarm.state_machine.timing import base_timing, resolve_timing, timing_from_snapshot
from alarm.tests.settings_test_utils import set_profile_setting, set_profile_settings


class TimingTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, delay_time=1, arming_time=2, trigger_time=3)

    def test_resolve_timing_applies_state_overrides(self):
        set_profile_setting(self.profile, "state_overrides", {AlarmState.ARMED_AWAY: {"arming_time": 99}})

        timing = resolve_timing(self.profile, AlarmState.ARMED_AWAY)
        self.assertEqual(timing.delay_time, 1)
        self.assertEqual(timing.arming_time, 99)
        self.assertEqual(timing.trigger_time, 3)

    def test_resolve_timing_ignores_invalid_overrides_shape(self):
        set_profile_setting(self.profile, "state_overrides", ["not-a-dict"])

        timing = resolve_timing(self.profile, AlarmState.ARMED_AWAY)
        self.assertEqual(timing, base_timing(self.profile))

    def test_resolve_timing_ignores_non_dict_override_value(self):
        set_profile_setting(self.profile, "state_overrides", {AlarmState.ARMED_AWAY: "nope"})

        timing = resolve_timing(self.profile, AlarmState.ARMED_AWAY)
        self.assertEqual(timing, base_timing(self.profile))

    def test_timing_from_snapshot_applies_partial_snapshot(self):
        snapshot = AlarmStateSnapshot.objects.create(
            current_state=AlarmState.DISARMED,
            previous_state=None,
            target_armed_state=None,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=None,
            last_transition_reason="test",
            timing_snapshot={"arming_time": 55},
        )
        timing = timing_from_snapshot(snapshot)
        self.assertEqual(timing.delay_time, 1)
        self.assertEqual(timing.arming_time, 55)
        self.assertEqual(timing.trigger_time, 3)
