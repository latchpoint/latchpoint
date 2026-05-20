from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState, AlarmStateSnapshot
from alarm.state_machine.errors import TransitionError
from alarm.state_machine.snapshot_store import transition as do_transition
from alarm.state_machine.transitions import arm, cancel_arming, disarm, timer_expired, trigger
from alarm.tests.settings_test_utils import set_profile_settings


class TransitionEdgeCaseTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, code_arm_required=False)
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
        )

    def test_timer_expired_is_noop_without_exit_at(self):
        self._create_snapshot(state=AlarmState.DISARMED, exit_at=None)
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

    def test_timer_expired_is_noop_when_exit_at_in_future(self):
        self._create_snapshot(
            state=AlarmState.ARMING,
            exit_at=timezone.now() + timedelta(seconds=10),
            target_armed_state=AlarmState.ARMED_AWAY,
        )
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)

    def test_cancel_arming_raises_when_not_arming(self):
        self._create_snapshot(state=AlarmState.DISARMED)
        with self.assertRaises(TransitionError):
            cancel_arming(user=self.user)

    def test_trigger_raises_while_disarmed(self):
        self._create_snapshot(state=AlarmState.DISARMED)
        with self.assertRaises(TransitionError):
            trigger(user=self.user)

    def test_trigger_noops_when_already_triggered(self):
        self._create_snapshot(
            state=AlarmState.TRIGGERED,
            exit_at=timezone.now() + timedelta(seconds=10),
            previous_state=AlarmState.ARMED_AWAY,
        )
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
        set_profile_settings(self.profile, code_arm_required=False)
        self.user = User.objects.create_user(email="timer@example.com", password="pass")

    def _create_snapshot(self, *, state: str, exit_at=None, target_armed_state=None, previous_state=None):
        return AlarmStateSnapshot.objects.create(
            current_state=state,
            previous_state=previous_state,
            target_armed_state=target_armed_state,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=exit_at,
            last_transition_reason="init",
        )

    def test_pending_to_triggered_on_timer_expired(self):
        self._create_snapshot(
            state=AlarmState.PENDING,
            exit_at=timezone.now() - timedelta(seconds=1),
            previous_state=AlarmState.ARMED_AWAY,
        )
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.TRIGGERED)

    def test_triggered_with_exit_at_returns_to_previous_armed_state(self):
        # Post-ADR-0095: TRIGGERED only auto-exits when an explicit ``exit_at`` is set
        # (e.g. via ``set_state(triggered, exit_at=X)``). When it does, it returns to
        # the previous armed state — there's no more ``disarm_after_trigger`` knob.
        self._create_snapshot(
            state=AlarmState.TRIGGERED,
            exit_at=timezone.now() - timedelta(seconds=1),
            previous_state=AlarmState.ARMED_AWAY,
        )
        snapshot = timer_expired()
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_AWAY)


class ArmingTransitionTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, code_arm_required=False)
        self.user = User.objects.create_user(email="arming@example.com", password="pass")

    def test_arm_to_armed_immediately_when_no_arming_time(self):
        disarm(reason="setup")
        snapshot = arm(target_state=AlarmState.ARMED_HOME, user=self.user, reason="test")
        self.assertEqual(snapshot.current_state, AlarmState.ARMED_HOME)

    def test_arm_records_armed_event_when_no_exit_delay(self):
        disarm(reason="setup")
        arm(target_state=AlarmState.ARMED_AWAY, user=self.user, reason="test")
        self.assertTrue(AlarmEvent.objects.filter(event_type=AlarmEventType.ARMED).exists())

    def test_arm_records_state_changed_event_when_entering_arming(self):
        disarm(reason="setup")
        arm(target_state=AlarmState.ARMED_AWAY, arming_time_seconds=10, user=self.user, reason="test")
        self.assertTrue(AlarmEvent.objects.filter(event_type=AlarmEventType.STATE_CHANGED).exists())
