from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from accounts.use_cases import code_validation
from alarm import services
from alarm.state_machine import errors as sm_errors


class ServicesValidateUserCodeWrapperTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="svcwrap@example.com", password="pass")

    @patch("accounts.use_cases.code_validation.validate_user_code")
    def test_maps_code_required_error(self, mock_validate):
        mock_validate.side_effect = code_validation.CodeRequiredError("Code is required.")
        with self.assertRaises(sm_errors.CodeRequiredError) as ctx:
            services.validate_user_code(user=self.user, raw_code=None)
        self.assertEqual(str(ctx.exception), "Code is required.")

    @patch("accounts.use_cases.code_validation.validate_user_code")
    def test_maps_invalid_code_error(self, mock_validate):
        mock_validate.side_effect = code_validation.InvalidCodeError("Invalid code.")
        with self.assertRaises(sm_errors.InvalidCodeError) as ctx:
            services.validate_user_code(user=self.user, raw_code="9999")
        self.assertEqual(str(ctx.exception), "Invalid code.")

    @patch("accounts.use_cases.code_validation.validate_user_code")
    @patch("alarm.services.timezone.now")
    def test_passes_services_timezone_now_through(self, mock_now, mock_validate):
        fixed = datetime(2025, 1, 1, 12, 0, tzinfo=dt_timezone.utc)
        mock_now.return_value = fixed

        class _Result:
            def __init__(self):
                self.code = object()

        captured = {}

        def _side_effect(*, user, raw_code, now):
            captured["user_id"] = user.id
            captured["raw_code"] = raw_code
            captured["now"] = now
            return _Result()

        mock_validate.side_effect = _side_effect
        services.validate_user_code(user=self.user, raw_code="1234")
        self.assertEqual(captured["user_id"], self.user.id)
        self.assertEqual(captured["raw_code"], "1234")
        self.assertEqual(captured["now"], fixed)

