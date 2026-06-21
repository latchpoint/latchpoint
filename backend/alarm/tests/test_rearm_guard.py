from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from alarm import rearm_guard
from alarm.models import AlarmSettingsProfile, AlarmState, SystemConfig
from alarm.state_machine.transitions import arm, disarm
from alarm.tests.settings_test_utils import set_profile_settings


class RearmGuardHelperTests(TestCase):
    """Unit behavior of the post-disarm re-arm guard helper."""

    def setUp(self):
        cache.clear()

    def test_not_blocked_when_never_marked(self):
        blocked, remaining = rearm_guard.recently_disarmed()
        self.assertFalse(blocked)
        self.assertEqual(remaining, 0)

    def test_blocked_within_window_after_mark(self):
        rearm_guard.mark_disarmed()
        blocked, remaining = rearm_guard.recently_disarmed()
        self.assertTrue(blocked)
        # Default window is 5s; only microseconds have elapsed.
        self.assertGreaterEqual(remaining, 1)
        self.assertLessEqual(remaining, 5)

    def test_disabled_when_window_is_zero(self):
        SystemConfig.objects.create(
            key="alarm.rearm_guard_seconds", name="Re-arm guard (seconds)", value_type="integer", value=0
        )
        rearm_guard.mark_disarmed()  # no-op when disabled
        blocked, remaining = rearm_guard.recently_disarmed()
        self.assertFalse(blocked)
        self.assertEqual(remaining, 0)


class DisarmOpensRearmWindowTests(TestCase):
    """The state machine's disarm() opens the guard window on commit."""

    def setUp(self):
        cache.clear()
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, delay_time=30, arming_time=0, trigger_time=20)

    def test_disarm_marks_recently_disarmed_after_commit(self):
        arm(target_state=AlarmState.ARMED_AWAY, user=None, code=None, reason="test")
        # on_commit callbacks only fire on a real commit; capture+execute them.
        with self.captureOnCommitCallbacks(execute=True):
            disarm(reason="test")
        blocked, _ = rearm_guard.recently_disarmed()
        self.assertTrue(blocked)

    def test_noop_disarm_when_already_disarmed_does_not_open_window(self):
        # Already disarmed -> disarm() early-returns without scheduling mark_disarmed.
        with self.captureOnCommitCallbacks(execute=True):
            disarm(reason="test")
        blocked, _ = rearm_guard.recently_disarmed()
        self.assertFalse(blocked)
