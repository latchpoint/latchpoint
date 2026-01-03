from __future__ import annotations

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Sensor
from alarm.state_machine.snapshot_store import get_snapshot_for_update, set_previous_armed_state, transition
from alarm.state_machine.timing import base_timing
from alarm.tests.settings_test_utils import set_profile_settings


class SnapshotStoreTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(self.profile, delay_time=11, arming_time=22, trigger_time=33)

    def test_get_snapshot_for_update_bootstraps(self):
        with transaction.atomic():
            snapshot = get_snapshot_for_update()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertEqual(snapshot.last_transition_reason, "bootstrap")
        self.assertEqual(snapshot.timing_snapshot, base_timing(self.profile).as_dict())

    def test_get_snapshot_for_update_returns_existing(self):
        existing = AlarmStateSnapshot.objects.create(
            current_state=AlarmState.ARMED_AWAY,
            previous_state=AlarmState.DISARMED,
            target_armed_state=None,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=None,
            last_transition_reason="existing",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        with transaction.atomic():
            snapshot = get_snapshot_for_update()
        self.assertEqual(snapshot.id, existing.id)

    def test_transition_updates_snapshot_and_records_event(self):
        snapshot = AlarmStateSnapshot.objects.create(
            current_state=AlarmState.DISARMED,
            previous_state=None,
            target_armed_state=None,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=None,
            last_transition_reason="init",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        user = User.objects.create_user(email="snap@example.com", password="pass")
        sensor = Sensor.objects.create(name="Front Door", is_active=True, is_entry_point=True)
        now = timezone.now()

        transition(
            snapshot=snapshot,
            state_to=AlarmState.ARMING,
            now=now,
            user=user,
            sensor=sensor,
            reason="arm",
            metadata={"source": "test"},
        )
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.ARMING)
        self.assertEqual(snapshot.previous_state, AlarmState.DISARMED)
        self.assertEqual(snapshot.last_transition_reason, "arm")
        self.assertEqual(snapshot.last_transition_by_id, user.id)

        event = AlarmEvent.objects.latest("id")
        self.assertEqual(event.event_type, AlarmEventType.STATE_CHANGED)
        self.assertEqual(event.state_from, AlarmState.DISARMED)
        self.assertEqual(event.state_to, AlarmState.ARMING)
        self.assertEqual(event.user_id, user.id)
        self.assertEqual(event.sensor_id, sensor.id)
        self.assertEqual(event.metadata, {"source": "test"})

    def test_transition_can_skip_previous_state_update(self):
        snapshot = AlarmStateSnapshot.objects.create(
            current_state=AlarmState.ARMED_AWAY,
            previous_state=AlarmState.ARMED_HOME,
            target_armed_state=None,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=None,
            last_transition_reason="init",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        now = timezone.now()
        transition(
            snapshot=snapshot,
            state_to=AlarmState.DISARMED,
            now=now,
            reason="disarm",
            update_previous=False,
        )
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)
        self.assertEqual(snapshot.previous_state, AlarmState.ARMED_HOME)

    def test_set_previous_armed_state_sets_armed(self):
        snapshot = AlarmStateSnapshot.objects.create(
            current_state=AlarmState.ARMED_AWAY,
            previous_state=None,
            target_armed_state=None,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=None,
            last_transition_reason="init",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        set_previous_armed_state(snapshot)
        self.assertEqual(snapshot.previous_state, AlarmState.ARMED_AWAY)

    def test_set_previous_armed_state_sets_target_when_arming(self):
        snapshot = AlarmStateSnapshot.objects.create(
            current_state=AlarmState.ARMING,
            previous_state=None,
            target_armed_state=AlarmState.ARMED_HOME,
            settings_profile=self.profile,
            entered_at=timezone.now(),
            exit_at=None,
            last_transition_reason="init",
            timing_snapshot=base_timing(self.profile).as_dict(),
        )
        set_previous_armed_state(snapshot)
        self.assertEqual(snapshot.previous_state, AlarmState.ARMED_HOME)
