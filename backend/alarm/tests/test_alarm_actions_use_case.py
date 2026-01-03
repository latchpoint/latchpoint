from __future__ import annotations

from django.contrib.auth.hashers import make_password
from django.test import TestCase

from accounts.models import User, UserCode
from alarm.models import AlarmEvent, AlarmEventType, AlarmSettingsProfile, AlarmState
from alarm.tests.settings_test_utils import set_profile_settings
from alarm.use_cases.alarm_actions import (
    CodeRequired,
    InvalidCode,
    InvalidTargetState,
    arm_alarm,
    disarm_alarm,
)


class ArmAlarmUseCaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="arm@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=30,
            trigger_time=60,
            code_arm_required=True,
        )
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("1234"),
            label="Test Code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )

    def test_arm_with_invalid_target_state_raises(self):
        with self.assertRaises(InvalidTargetState):
            arm_alarm(user=self.user, target_state="invalid", raw_code="1234")

    def test_arm_without_code_when_required_raises_code_required(self):
        with self.assertRaises(CodeRequired):
            arm_alarm(user=self.user, target_state=AlarmState.ARMED_AWAY, raw_code=None)

    def test_arm_with_invalid_code_raises_invalid_code(self):
        with self.assertRaises(InvalidCode):
            arm_alarm(user=self.user, target_state=AlarmState.ARMED_AWAY, raw_code="9999")

    def test_arm_with_valid_code_succeeds(self):
        snapshot = arm_alarm(user=self.user, target_state=AlarmState.ARMED_AWAY, raw_code="1234")
        self.assertIn(snapshot.current_state, [AlarmState.ARMING, AlarmState.ARMED_AWAY])

    def test_arm_records_code_used_event(self):
        arm_alarm(user=self.user, target_state=AlarmState.ARMED_AWAY, raw_code="1234")
        self.assertTrue(
            AlarmEvent.objects.filter(
                event_type=AlarmEventType.CODE_USED,
                metadata__action="arm",
            ).exists()
        )

    def test_arm_records_failed_code_event_on_invalid_code(self):
        try:
            arm_alarm(user=self.user, target_state=AlarmState.ARMED_AWAY, raw_code="9999")
        except InvalidCode:
            pass
        self.assertTrue(
            AlarmEvent.objects.filter(
                event_type=AlarmEventType.FAILED_CODE,
                metadata__action="arm",
            ).exists()
        )

    def test_arm_without_code_when_not_required_succeeds(self):
        set_profile_settings(self.profile, code_arm_required=False)
        snapshot = arm_alarm(user=self.user, target_state=AlarmState.ARMED_AWAY, raw_code=None)
        self.assertIn(snapshot.current_state, [AlarmState.ARMING, AlarmState.ARMED_AWAY])


class DisarmAlarmUseCaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="disarm@example.com", password="pass")
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            delay_time=30,
            arming_time=30,
            trigger_time=60,
        )
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password("1234"),
            label="Test Code",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=4,
            is_active=True,
        )

    def test_disarm_without_code_raises_code_required(self):
        with self.assertRaises(CodeRequired):
            disarm_alarm(user=self.user, raw_code=None)

    def test_disarm_with_invalid_code_raises_invalid_code(self):
        with self.assertRaises(InvalidCode):
            disarm_alarm(user=self.user, raw_code="9999")

    def test_disarm_with_valid_code_succeeds(self):
        snapshot = disarm_alarm(user=self.user, raw_code="1234")
        self.assertEqual(snapshot.current_state, AlarmState.DISARMED)

    def test_disarm_records_code_used_event(self):
        disarm_alarm(user=self.user, raw_code="1234")
        self.assertTrue(
            AlarmEvent.objects.filter(
                event_type=AlarmEventType.CODE_USED,
                metadata__action="disarm",
            ).exists()
        )

    def test_disarm_records_failed_code_event_on_invalid_code(self):
        try:
            disarm_alarm(user=self.user, raw_code="9999")
        except InvalidCode:
            pass
        self.assertTrue(
            AlarmEvent.objects.filter(
                event_type=AlarmEventType.FAILED_CODE,
                metadata__action="disarm",
            ).exists()
        )
