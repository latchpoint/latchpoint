from __future__ import annotations

from datetime import datetime, time, timezone as dt_timezone

from django.contrib.auth.hashers import make_password
from django.test import TestCase

from accounts.models import User, UserCode
from accounts.use_cases import code_validation


class CodeValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="codeval@example.com", password="pass")
        self.raw_code = "1234"
        self.code = UserCode.objects.create(
            user=self.user,
            code_hash=make_password(self.raw_code),
            label="Test",
            code_type=UserCode.CodeType.PERMANENT,
            pin_length=len(self.raw_code),
            is_active=True,
        )

    def test_requires_code(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.CodeRequiredError):
            code_validation.validate_user_code(user=self.user, raw_code=None, now=now)

    def test_rejects_invalid_length(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError):
            code_validation.validate_user_code(user=self.user, raw_code="123", now=now)
        with self.assertRaises(code_validation.InvalidCodeError):
            code_validation.validate_user_code(user=self.user, raw_code="123456789", now=now)

    def test_accepts_valid_permanent_code(self):
        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_user_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)

    def test_temporary_code_rejects_time_window_miss(self):
        self.code.code_type = UserCode.CodeType.TEMPORARY
        self.code.window_start = time(9, 0, 0)
        self.code.window_end = time(10, 0, 0)
        self.code.save(update_fields=["code_type", "window_start", "window_end"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError) as ctx:
            code_validation.validate_user_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(str(ctx.exception), "Code is not valid at this time.")

    def test_temporary_code_rejects_expired(self):
        self.code.code_type = UserCode.CodeType.TEMPORARY
        self.code.end_at = datetime(2025, 1, 1, 11, 0, tzinfo=dt_timezone.utc)
        self.code.save(update_fields=["code_type", "end_at"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        with self.assertRaises(code_validation.InvalidCodeError) as ctx:
            code_validation.validate_user_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(str(ctx.exception), "Code has expired.")

    def test_invalid_user_timezone_falls_back_to_utc(self):
        self.user.timezone = "Not/AZone"
        self.user.save(update_fields=["timezone"])

        self.code.code_type = UserCode.CodeType.TEMPORARY
        self.code.window_start = time(11, 0, 0)
        self.code.window_end = time(13, 0, 0)
        self.code.save(update_fields=["code_type", "window_start", "window_end"])

        now = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        result = code_validation.validate_user_code(user=self.user, raw_code=self.raw_code, now=now)
        self.assertEqual(result.code.id, self.code.id)

