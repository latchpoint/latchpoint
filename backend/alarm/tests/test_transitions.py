from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm import services
from alarm.models import AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Sensor
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
        snapshot = services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)
        self.assertEqual(snapshot.target_armed_state, AlarmState.ARMED_AWAY)
        self.assertIsNotNone(snapshot.exit_at)

    def test_arm_home_zero_exit_delay_arms_immediately(self):
        set_profile_setting(self.profile, "state_overrides", {AlarmState.ARMED_HOME: {"arming_time": 0}})
        snapshot = services.arm(target_state=AlarmState.ARMED_HOME, user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_HOME)
        self.assertIsNone(snapshot.exit_at)

    def test_timer_expired_arming_to_armed(self):
        snapshot = services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

    def test_entry_sensor_goes_pending(self):
        snapshot = services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot = services.sensor_triggered(sensor=self.entry_sensor)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        self.assertEqual(snapshot.previous_state, AlarmState.ARMED_AWAY)
        self.assertIsNotNone(snapshot.exit_at)

    def test_non_entry_sensor_triggers(self):
        snapshot = services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot = services.sensor_triggered(sensor=self.motion_sensor)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)
        self.assertEqual(snapshot.previous_state, AlarmState.ARMED_AWAY)
        self.assertIsNotNone(snapshot.exit_at)

    def test_trigger_timer_returns_to_armed(self):
        snapshot = services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot = services.sensor_triggered(sensor=self.motion_sensor)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

    def test_trigger_timer_disarms_when_configured(self):
        set_profile_setting(self.profile, "disarm_after_trigger", True)
        snapshot = services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot = services.sensor_triggered(sensor=self.motion_sensor)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

    def test_disarm_clears_target(self):
        snapshot = services.arm(target_state=AlarmState.ARMED_AWAY, user=self.user)
        snapshot.exit_at = timezone.now() - timedelta(seconds=1)
        snapshot.save(update_fields=["exit_at"])
        snapshot = services.timer_expired()
        snapshot = services.disarm(user=self.user)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertIsNone(snapshot.target_armed_state)


class AlarmSnapshotBootstrapTests(TestCase):
    def test_bootstrap_creates_snapshot(self):
        AlarmSettingsProfile.objects.create(
            name="Default",
            is_active=True,
        )
        snapshot = services.timer_expired()
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertTrue(AlarmStateSnapshot.objects.exists())
