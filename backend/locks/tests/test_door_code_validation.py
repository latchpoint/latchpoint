from __future__ import annotations

from datetime import datetime, time, timezone as dt_timezone

from django.contrib.auth.hashers import make_password
from django.test import TestCase

from accounts.models import User
from locks.models import DoorCode, DoorCodeLockAssignment
from locks.use_cases import code_validation


class DoorCodeValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="codeval@example.com", password="pass")
        self.raw_code = "1234"
        self.code = DoorCode.objects.create(
            user=self.user,
            code_hash=make_password(self.raw_code),
            label="Test",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=len(self.raw_code),
            is_active=True,
        )
        DoorCodeLockAssignment.objects.create(
            door_code=self.code,
            lock_entity_id="lock.front_door",
        )

    def test_requires_code(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.CodeRequiredError):
            code_validation.validate_door_code(user=self.user, raw_code=None, now=now)

    def test_rejects_invalid_length(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError):
            code_validation.validate_door_code(user=self.user, raw_code="123", now=now)
        with self.assertRaises(code_validation.InvalidCodeError):
            code_validation.validate_door_code(user=self.user, raw_code="123456789", now=now)

    def test_accepts_valid_permanent_code(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)

    def test_validates_code_for_specific_lock(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_door_code(
            user=self.user,
            raw_code=self.raw_code,
            lock_entity_id="lock.front_door",
            now=now,
        )
        self.assertEqual(result.code.id, self.code.id)

    def test_rejects_code_not_assigned_to_lock(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError):
            code_validation.validate_door_code(
                user=self.user,
                raw_code=self.raw_code,
                lock_entity_id="lock.back_door",
                now=now,
            )

    def test_temporary_code_rejects_time_window_miss(self):
        self.code.code_type = DoorCode.CodeType.TEMPORARY
        self.code.window_start = time(9, 0, 0)
        self.code.window_end = time(10, 0, 0)
        self.code.save(update_fields=["code_type", "window_start", "window_end"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError) as ctx:
            code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(str(ctx.exception), "Code is not valid at this time.")

    def test_temporary_code_accepts_within_time_window(self):
        self.code.code_type = DoorCode.CodeType.TEMPORARY
        self.code.window_start = time(9, 0, 0)
        self.code.window_end = time(17, 0, 0)
        self.code.save(update_fields=["code_type", "window_start", "window_end"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)

    def test_temporary_code_rejects_expired(self):
        self.code.code_type = DoorCode.CodeType.TEMPORARY
        self.code.end_at = datetime(2025, 1, 1, 11, 0, tzinfo=dt_timezone.utc)
        self.code.save(update_fields=["code_type", "end_at"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.CodeExpiredError) as ctx:
            code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(str(ctx.exception), "Code has expired.")

    def test_temporary_code_rejects_not_yet_active(self):
        self.code.code_type = DoorCode.CodeType.TEMPORARY
        self.code.start_at = datetime(2025, 1, 2, 0, 0, tzinfo=dt_timezone.utc)
        self.code.save(update_fields=["code_type", "start_at"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError) as ctx:
            code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(str(ctx.exception), "Code is not active yet.")

    def test_temporary_code_rejects_wrong_day_of_week(self):
        self.code.code_type = DoorCode.CodeType.TEMPORARY
        self.code.days_of_week = 1 << 5  # Saturday only (Mon=0, ..., Sat=5)
        self.code.save(update_fields=["code_type", "days_of_week"])

        # January 1, 2025 is a Wednesday (weekday=2)
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError) as ctx:
            code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(str(ctx.exception), "Code is not valid today.")

    def test_temporary_code_accepts_correct_day_of_week(self):
        self.code.code_type = DoorCode.CodeType.TEMPORARY
        self.code.days_of_week = 1 << 2  # Wednesday only (Mon=0, ..., Wed=2)
        self.code.save(update_fields=["code_type", "days_of_week"])

        # January 1, 2025 is a Wednesday
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)

    def test_code_with_max_uses_exhausted(self):
        self.code.max_uses = 5
        self.code.uses_count = 5
        self.code.save(update_fields=["max_uses", "uses_count"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.CodeExhaustedError) as ctx:
            code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(str(ctx.exception), "Code has reached maximum uses.")

    def test_code_with_max_uses_still_available(self):
        self.code.max_uses = 5
        self.code.uses_count = 4
        self.code.save(update_fields=["max_uses", "uses_count"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)

    def test_invalid_user_timezone_falls_back_to_utc(self):
        self.user.timezone = "Not/AZone"
        self.user.save(update_fields=["timezone"])

        self.code.code_type = DoorCode.CodeType.TEMPORARY
        self.code.window_start = time(11, 0, 0)
        self.code.window_end = time(13, 0, 0)
        self.code.save(update_fields=["code_type", "window_start", "window_end"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)

    def test_one_time_code_validates(self):
        self.code.code_type = DoorCode.CodeType.ONE_TIME
        self.code.save(update_fields=["code_type"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_door_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)


class DoorCodeUsageRecordingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="usage@example.com", password="pass")
        self.raw_code = "1234"
        self.code = DoorCode.objects.create(
            user=self.user,
            code_hash=make_password(self.raw_code),
            label="Test",
            code_type=DoorCode.CodeType.PERMANENT,
            pin_length=len(self.raw_code),
            is_active=True,
        )

    def test_record_usage_increments_count(self):
        initial_count = self.code.uses_count
        code_validation.record_door_code_usage(code=self.code, lock_entity_id="lock.front_door")

        self.code.refresh_from_db()
        self.assertEqual(self.code.uses_count, initial_count + 1)
        self.assertEqual(self.code.last_used_lock, "lock.front_door")
        self.assertIsNotNone(self.code.last_used_at)

    def test_one_time_code_deactivated_after_use(self):
        self.code.code_type = DoorCode.CodeType.ONE_TIME
        self.code.save()

        code_validation.record_door_code_usage(code=self.code, lock_entity_id="lock.front_door")

        self.code.refresh_from_db()
        self.assertFalse(self.code.is_active)

    def test_failed_usage_does_not_increment_count(self):
        initial_count = self.code.uses_count
        code_validation.record_door_code_usage(code=self.code, lock_entity_id="lock.front_door", success=False)

        self.code.refresh_from_db()
        self.assertEqual(self.code.uses_count, initial_count)
