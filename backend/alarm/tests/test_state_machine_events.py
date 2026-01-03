from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.contrib.auth.hashers import make_password
from django.test import TestCase

from accounts.models import User, UserCode
from alarm.models import AlarmEventType, AlarmSettingsProfile, AlarmState, AlarmStateSnapshot, Sensor
from alarm.state_machine.events import record_code_used, record_failed_code, record_sensor_event, record_state_event


class StateMachineEventsTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        self.snapshot = AlarmStateSnapshot.objects.create(
            current_state=AlarmState.DISARMED,
            previous_state=None,
            target_armed_state=None,
            settings_profile=self.profile,
            entered_at=datetime(2025, 1, 1, 0, 0, tzinfo=dt_timezone.utc),
            exit_at=None,
            last_transition_reason="init",
            timing_snapshot={},
        )
        self.user = User.objects.create_user(email="events@example.com", password="pass")
        self.raw_code = "1234"
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password(self.raw_code),
            label="Test",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=len(self.raw_code),
            is_active=True,
        )

    def test_record_state_event_maps_armed(self):
        event = record_state_event(
            snapshot=self.snapshot,
            state_from=AlarmState.DISARMED,
            state_to=AlarmState.ARMED_AWAY,
            user=self.user,
            metadata={"x": 1},
            timestamp=datetime(2025, 1, 1, 1, 0, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(event.event_type, AlarmEventType.ARMED)
        self.assertEqual(event.metadata, {"x": 1})

    def test_record_code_used_increments_uses(self):
        now = datetime(2025, 1, 1, 2, 0, tzinfo=dt_timezone.utc)
        event = record_code_used(user=self.user, code=self.code, action="arm", timestamp=now)
        self.code.refresh_from_db()
        self.assertEqual(self.code.uses_count, 1)
        self.assertEqual(self.code.last_used_at, now)
        self.assertEqual(event.event_type, AlarmEventType.CODE_USED)
        self.assertEqual(event.metadata["action"], "arm")

    def test_record_failed_code_records_action(self):
        now = datetime(2025, 1, 1, 3, 0, tzinfo=dt_timezone.utc)
        event = record_failed_code(user=self.user, action="disarm", metadata={"reason": "bad"}, timestamp=now)
        self.assertEqual(event.event_type, AlarmEventType.FAILED_CODE)
        self.assertEqual(event.metadata, {"action": "disarm", "reason": "bad"})

    def test_record_sensor_event_marks_entry_point(self):
        sensor = Sensor.objects.create(name="Front Door", is_active=True, is_entry_point=True)
        event = record_sensor_event(sensor)
        self.assertEqual(event.event_type, AlarmEventType.SENSOR_TRIGGERED)
        self.assertEqual(event.metadata["is_entry_point"], True)

