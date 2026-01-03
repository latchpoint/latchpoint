from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from accounts.use_cases.user_codes import create_user_code
from alarm.models import AlarmSettingsProfile, AlarmState
from alarm.state_machine import transitions
from alarm.tests.settings_test_utils import set_profile_settings


class HomeAssistantStateChangeNotificationsTests(TestCase):
    def test_sends_notification_when_enabled_and_state_selected(self):
        user = User.objects.create_user(email="notify@example.com", password="pass")
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            profile,
            delay_time=0,
            arming_time=0,
            trigger_time=0,
            code_arm_required=False,
            home_assistant_notify={
                "enabled": True,
                "services": ["notify.notify", "notify.mobile_app_phone"],
                "cooldown_seconds": 0,
                "states": [AlarmState.DISARMED],
            },
        )

        with patch("integrations_home_assistant.tasks.ha_gateway") as mock_gateway:
            with self.captureOnCommitCallbacks(execute=True):
                transitions.arm(target_state=AlarmState.ARMED_AWAY, user=user)
                transitions.disarm(user=user)

        self.assertEqual(mock_gateway.call_service.call_count, 2)
        for call in mock_gateway.call_service.call_args_list:
            kwargs = call.kwargs
            self.assertEqual(kwargs["domain"], "notify")
            self.assertIn("service", kwargs)
            self.assertIn("service_data", kwargs)
            self.assertEqual(kwargs["service_data"]["data"]["state_to"], AlarmState.DISARMED)
            # Notifications should never include user identity (email/username).
            message = kwargs["service_data"]["message"]
            self.assertNotIn("By", message)
            self.assertNotIn("notify@example.com", message)

    def test_skips_notification_when_state_not_selected(self):
        user = User.objects.create_user(email="notify2@example.com", password="pass")
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            profile,
            delay_time=0,
            arming_time=0,
            trigger_time=0,
            code_arm_required=False,
            home_assistant_notify={
                "enabled": True,
                "services": ["notify.notify"],
                "cooldown_seconds": 0,
                "states": [],
            },
        )

        with patch("integrations_home_assistant.tasks.ha_gateway") as mock_gateway:
            with self.captureOnCommitCallbacks(execute=True):
                transitions.arm(target_state=AlarmState.ARMED_AWAY, user=user)
                transitions.disarm(user=user)

        mock_gateway.call_service.assert_not_called()

    def test_notification_prefers_code_label_over_user_identity(self):
        user = User.objects.create_user(email="notify3@example.com", password="pass")
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            profile,
            delay_time=0,
            arming_time=0,
            trigger_time=0,
            code_arm_required=False,
            home_assistant_notify={
                "enabled": True,
                "services": ["notify.notify"],
                "cooldown_seconds": 0,
                "states": [AlarmState.DISARMED],
            },
        )
        code = create_user_code(user=user, raw_code="1234", label="Front Door")

        with patch("integrations_home_assistant.tasks.ha_gateway") as mock_gateway:
            with self.captureOnCommitCallbacks(execute=True):
                transitions.arm(target_state=AlarmState.ARMED_AWAY, user=user)
                transitions.disarm(user=user, code=code)

        call = mock_gateway.call_service.call_args
        message = call.kwargs["service_data"]["message"]
        self.assertIn("By Front Door.", message)
        self.assertNotIn("notify3@example.com", message)
