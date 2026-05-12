from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.models import AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Sensor
from alarm.state_machine.transitions import (
    arm,
    disarm,
    sensor_triggered,
    timer_expired,
    trigger_with_delay,
)
from alarm.tests.settings_test_utils import set_profile_setting, set_profile_settings


class AlarmTransitionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=10,
            trigger_time=20,
            code_arm_required=True,
        )
        self.entry_sensor = Sensor.objects.create(
            name="Front Door",
            is_active=True,
            is_entry_point=True,
        )
        self.motion_sensor = Sensor.objects.create(
            name="Living Motion",
            is_active=True,
            is_entry_point=False,
        )

    def test_arm_to_arming(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)
        self.assertEqual(snapshot.target_armed_state, AlarmState.ARMED_AWAY)
        self.assertIsNotNone(snapshot.exit_at)

    def test_arm_home_zero_exit_delay_arms_immediately(self):
        set_profile_setting(self.profile, "state_overrides", {AlarmState.ARMED_HOME: {"arming_time": 0}})
        snapshot = arm(target_state=AlarmState.ARMED_HOME, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_HOME)
        self.assertIsNone(snapshot.exit_at)

    def test_timer_expired_arming_to_armed(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

    def test_entry_sensor_goes_pending(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot = sensor_triggered(sensor=self.entry_sensor)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        self.assertEqual(snapshot.previous_state, AlarmState.ARMED_AWAY)
        self.assertIsNotNone(snapshot.exit_at)

    def test_non_entry_sensor_triggers(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot = sensor_triggered(sensor=self.motion_sensor)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)
        self.assertEqual(snapshot.previous_state, AlarmState.ARMED_AWAY)
        self.assertIsNotNone(snapshot.exit_at)

    def test_trigger_timer_returns_to_armed(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot = sensor_triggered(sensor=self.motion_sensor)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

    def test_trigger_timer_disarms_when_configured(self):
        set_profile_setting(self.profile, "disarm_after_trigger", True)
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot = sensor_triggered(sensor=self.motion_sensor)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

    def test_disarm_clears_target(self):
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = timer_expired()
        snapshot = disarm(user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertIsNone(snapshot.target_armed_state)

    def test_trigger_time_zero_keeps_alarm_triggered_until_disarmed(self):
        set_profile_setting(self.profile, "trigger_time", 0)
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        timer_expired()
        snapshot = sensor_triggered(sensor=self.motion_sensor)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)
        self.assertIsNone(snapshot.exit_at)
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)
        snapshot = disarm(user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)


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


class TriggerWithDelayTests(TestCase):
    """Rule-driven entry-delay (ADR-0091 revised, Option 1 path).

    Enters PENDING with a caller-supplied delay when the alarm is in an
    armed state; no-ops from every other state. Disarm during the wait
    returns to DISARMED. timer_expired() advances PENDING → TRIGGERED.
    """

    def setUp(self):
        self.user = User.objects.create_user(email="rule@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=0,
            trigger_time=20,
        )

    def _arm_to(self, state: str) -> AlarmStateSnapshot:
        snapshot = arm(target_state=state, user=self.user)
        snapshot.refresh_from_db()
        return snapshot

    def test_enters_pending_from_armed_away(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        before = timezone.now()
        snapshot = trigger_with_delay(delay_seconds=15, user=self.user, reason="rule:1")
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        self.assertIsNotNone(snapshot.exit_at)
        # exit_at should land ~15s in the future.
        delta = (snapshot.exit_at - before).total_seconds()
        self.assertGreaterEqual(delta, 14)
        self.assertLessEqual(delta, 17)

    def test_enters_pending_from_armed_home(self):
        self._arm_to(AlarmState.ARMED_HOME)
        snapshot = trigger_with_delay(delay_seconds=10)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)

    def test_noop_from_disarmed(self):
        # Snapshot stays DISARMED — rule firing from disarmed must not
        # coerce the alarm into PENDING.
        snapshot = trigger_with_delay(delay_seconds=10)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertIsNone(snapshot.exit_at)

    def test_noop_from_pending(self):
        # An existing PENDING (e.g. from a sensor trip) is not shortened or
        # extended by a rule's delay — first-countdown-wins.
        self._arm_to(AlarmState.ARMED_AWAY)
        sensor = Sensor.objects.create(name="Door", is_active=True, is_entry_point=True)
        snapshot = sensor_triggered(sensor=sensor)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        original_exit_at = snapshot.exit_at

        snapshot = trigger_with_delay(delay_seconds=5)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        self.assertEqual(snapshot.exit_at, original_exit_at)

    def test_noop_from_triggered(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        sensor = Sensor.objects.create(name="Motion", is_active=True, is_entry_point=False)
        snapshot = sensor_triggered(sensor=sensor)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

        snapshot = trigger_with_delay(delay_seconds=10)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

    def test_noop_from_arming(self):
        set_profile_setting(self.profile, "arming_time", 30)
        snapshot = arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)

        snapshot = trigger_with_delay(delay_seconds=10)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)

    def test_timer_expired_advances_pending_to_triggered(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        snapshot = trigger_with_delay(delay_seconds=5)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        # Fast-forward by force-setting exit_at into the past, then tick.
        AlarmStateSnapshot.objects.update(exit_at=timezone.now() - timedelta(seconds=1))
        snapshot = timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

    def test_disarm_during_wait_cancels(self):
        self._arm_to(AlarmState.ARMED_AWAY)
        snapshot = trigger_with_delay(delay_seconds=15)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)

        snapshot = disarm(user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
