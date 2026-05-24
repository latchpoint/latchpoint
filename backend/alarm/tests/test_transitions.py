from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.models import AlarmSettingsProfile, AlarmState, AlarmStateSnapshot
from alarm.state_machine.errors import TransitionError
from alarm.state_machine.transitions import (
    arm,
    disarm,
    set_state,
    timer_expired,
)
from alarm.tests.settings_test_utils import set_profile_settings


class AlarmTransitionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, code_arm_required=True)

    def test_arm_with_arming_time_enters_arming(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, arming_time_seconds=10, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)
        self.assertEqual(snapshot.target_armed_state, AlarmState.ARMED_AWAY)
        self.assertIsNotNone(snapshot.exit_at)

    def test_arm_without_arming_time_arms_immediately(self):
        snapshot = arm(target_state=AlarmState.ARMED_HOME, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_HOME)
        self.assertIsNone(snapshot.exit_at)

    def test_arm_with_zero_arming_time_arms_immediately(self):
        snapshot = arm(target_state=AlarmState.ARMED_HOME, arming_time_seconds=0, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_HOME)
        self.assertIsNone(snapshot.exit_at)

    def test_timer_expired_arming_to_armed(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, arming_time_seconds=10, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

    def test_disarm_clears_target(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, arming_time_seconds=10, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot = disarm(user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertIsNone(snapshot.target_armed_state)


class AlarmSnapshotBootstrapTests(TestCase):
    def test_bootstrap_creates_snapshot(self):
        AlarmSettingsProfile.objects.create(
            name="Default",
            is_active=True,
        )
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertTrue(AlarmStateSnapshot.objects.exists())


class SetStateTests(TestCase):
    """Direct alarm-state setter (ADR-0094 composable primitive).

    PENDING/TRIGGERED can be entered from any state (the operator wrote the rule).
    PENDING does NOT auto-advance unless an explicit ``exit_at`` is supplied.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="rule@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def _arm_to(self, state: str) -> AlarmStateSnapshot:
        snapshot = arm(target_state=state, user=self.user)
        snapshot.refresh_from_db()
        return snapshot

    def test_set_pending_from_armed_does_not_set_exit_at(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        snapshot = set_state(new_state=AlarmState.PENDING, user=self.user, reason="rule:1")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        self.assertIsNone(snapshot.exit_at)

    def test_set_pending_with_exit_at_auto_advances(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        exit_at = timezone.now() + timedelta(seconds=5)
        snapshot = set_state(new_state=AlarmState.PENDING, exit_at=exit_at, reason="rule:2")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        self.assertIsNotNone(snapshot.exit_at)
        AlarmStateSnapshot.objects.update(exit_at=timezone.now() - timedelta(seconds=1))
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

    def test_set_pending_from_disarmed_is_allowed(self):
        snapshot = set_state(new_state=AlarmState.PENDING, reason="rule:disarmed_pending")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)

    def test_set_triggered_from_disarmed_is_allowed(self):
        snapshot = set_state(new_state=AlarmState.TRIGGERED, reason="rule:panic")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

    def test_set_arming_is_rejected(self):
        with self.assertRaises(TransitionError):
            set_state(new_state=AlarmState.ARMING, reason="rule:bad")

    def test_set_state_to_current_state_is_idempotent(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        snapshot = set_state(new_state=AlarmState.ARMED_AWAY, reason="rule:idempotent")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

    def test_set_disarmed_delegates_to_disarm_cleanup(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        AlarmStateSnapshot.objects.update(target_armed_state=AlarmState.ARMED_HOME)
        snapshot = set_state(new_state=AlarmState.DISARMED, user=self.user, reason="rule:disarm")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertIsNone(snapshot.target_armed_state)

    def test_disarm_during_manual_pending_returns_to_disarmed(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        set_state(new_state=AlarmState.PENDING, reason="rule:enter_pending")
        snapshot = disarm(user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
