from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Sensor
from alarm.state_machine.errors import TransitionError
from alarm.state_machine.snapshot_store import transition as do_transition
from alarm.state_machine.transitions import cancel_arming, sensor_triggered, timer_expired, trigger
from alarm.state_machine.timing import base_timing
from alarm.tests.settings_test_utils import set_profile_settings


class TransitionEdgeCaseTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=5,
            arming_time=5,
            trigger_time=5,
            code_arm_required=False,
        )
        self.sensor = Sensor.objects.create(name="Front Door", is_active=True, is_entry_point=True)
        self.user = User.objects.create_user(email="edge@example.com", password="pass")

    def _create_snapshot(self, *, state: str, exit_at=None, target_armed_state=None, previous_state=None):
        return AlarmStateSnapshot.objects.create(
            current_state=state,
            previous_state=previous_state,
            target_armed_state=target_armed_state,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=exit_at,
            last_transition_reason="init",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )

    def test_timer_expired_is_noop_without_exit_at(self):
        self._create_snapshot(state=AlarmState.DISARMED, exit_at=None)
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

    def test_timer_expired_is_noop_when_exit_at_in_future(self):
        self._create_snapshot(state=AlarmState.ARMING, exit_at=timezone.now() + timedelta(seconds=10), target_armed_state=AlarmState.ARMED_AWAY)
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)

    def test_cancel_arming_raises_when_not_arming(self):
        self._create_snapshot(state=AlarmState.DISARMED)
        with self.assertRaises(TransitionError):
            cancel_arming(user=self.user)

    def test_sensor_triggered_does_not_transition_when_disarmed_but_records_event(self):
        self._create_snapshot(state=AlarmState.DISARMED)
        snapshot = sensor_triggered(sensor=self.sensor, user=self.user)
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertTrue(AlarmEvent.objects.filter(event_type=AlarmEventType.SENSOR_TRIGGERED, sensor=self.sensor).exists())

    def test_sensor_triggered_ignored_when_already_pending_but_records_event(self):
        self._create_snapshot(state=AlarmState.PENDING, exit_at=timezone.now() + timedelta(seconds=10), previous_state=AlarmState.ARMED_AWAY)
        snapshot = sensor_triggered(sensor=self.sensor, user=self.user)
        self.assertEqual(snapshot.current_state, AlarmState.PENDING)
        self.assertTrue(AlarmEvent.objects.filter(event_type=AlarmEventType.SENSOR_TRIGGERED, sensor=self.sensor).exists())

    def test_trigger_raises_while_disarmed(self):
        self._create_snapshot(state=AlarmState.DISARMED)
        with self.assertRaises(TransitionError):
            trigger(user=self.user)

    def test_trigger_noops_when_already_triggered(self):
        self._create_snapshot(state=AlarmState.TRIGGERED, exit_at=timezone.now() + timedelta(seconds=10), previous_state=AlarmState.ARMED_AWAY)
        snapshot = trigger(user=self.user)
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

    def test_trigger_sets_previous_state_when_arming(self):
        snapshot = self._create_snapshot(
            state=AlarmState.ARMING,
            exit_at=timezone.now() + timedelta(seconds=10),
            target_armed_state=AlarmState.ARMED_AWAY,
            previous_state=None,
        )
        before = snapshot.entered_at
        snapshot2 = trigger(user=self.user)
        snapshot2.refresh_from_db()
        self.assertEqual(snapshot2.current_state, AlarmState.TRIGGERED)
        self.assertEqual(snapshot2.previous_state, AlarmState.ARMED_AWAY)
        self.assertGreaterEqual(snapshot2.entered_at, before)

    def test_trigger_records_state_changed_event_for_unknown_transition_target(self):
        snapshot = self._create_snapshot(state=AlarmState.DISARMED)
        now = timezone.now()
        with transaction.atomic():
            do_transition(snapshot=snapshot, state_to="weird_state", now=now, reason="test")
        event = AlarmEvent.objects.latest("id")
        self.assertEqual(event.event_type, AlarmEventType.STATE_CHANGED)


class TimerTransitionTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=5,
            arming_time=5,
            trigger_time=5,
            code_arm_required=False,
            disarm_after_trigger=False,
        )
        self.sensor = Sensor.objects.create(name="Front Door", is_active=True, is_entry_point=True)
        self.motion_sensor = Sensor.objects.create(name="Motion", is_active=True, is_entry_point=False)
        self.user = User.objects.create_user(email="timer@example.com", password="pass")

    def _create_snapshot(self, *, state: str, exit_at=None, target_armed_state=None, previous_state=None):
        from alarm.state_machine.timing import base_timing
        return AlarmStateSnapshot.objects.create(
            current_state=state,
            previous_state=previous_state,
            target_armed_state=target_armed_state,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=exit_at,
            last_transition_reason="init",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )

    def test_pending_to_triggered_on_timer_expired(self):
        self._create_snapshot(
            state=AlarmState.PENDING,
            exit_at=timezone.now() - timedelta(seconds=1),
            previous_state=AlarmState.ARMED_AWAY,
        )
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

    def test_triggered_returns_to_armed_when_disarm_after_trigger_false(self):
        set_profile_settings(self.profile, disarm_after_trigger=False)
        self._create_snapshot(
            state=AlarmState.TRIGGERED,
            exit_at=timezone.now() - timedelta(seconds=1),
            previous_state=AlarmState.ARMED_AWAY,
        )
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)

    def test_triggered_disarms_when_disarm_after_trigger_true(self):
        set_profile_settings(self.profile, disarm_after_trigger=True)
        self._create_snapshot(
            state=AlarmState.TRIGGERED,
            exit_at=timezone.now() - timedelta(seconds=1),
            previous_state=AlarmState.ARMED_AWAY,
        )
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)


class ArmingTransitionTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=5,
            arming_time=10,
            trigger_time=5,
            code_arm_required=False,
        )
        self.user = User.objects.create_user(email="arming@example.com", password="pass")

    def test_arm_to_armed_immediately_when_arming_time_is_zero(self):
        from alarm.state_machine.transitions import arm, disarm
        set_profile_settings(
            self.profile,
            state_overrides={AlarmState.ARMED_HOME: {"arming_time": 0}},
        )
        disarm(reason="setup")  # Ensure we're disarmed
        snapshot = arm(target_state=AlarmState.ARMED_HOME, user=self.user, reason="test")
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_HOME)

    def test_arm_records_state_changed_event(self):
        from alarm.state_machine.transitions import arm, disarm
        disarm(reason="setup")
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user, reason="test")
        self.assertTrue(
            AlarmEvent.objects.filter(event_type=AlarmEventType.STATE_CHANGED).exists()
        )
