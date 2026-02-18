from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from alarm.models import AlarmState


class FrontendContractSmokeApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="contracts@example.com", password="pass")
        self.client.force_authenticate(self.user)

    def test_alarm_state_payload_keeps_required_frontend_keys(self):
        response = self.client.get(reverse("alarm-state"))
        self.assertEqual(response.status_code, 200)

        payload = response.json()["data"]
        for key in (
            "id",
            "current_state",
            "previous_state",
            "settings_profile",
            "entered_at",
            "exit_at",
            "last_transition_reason",
            "last_transition_by",
            "target_armed_state",
            "timing_snapshot",
        ):
            self.assertIn(key, payload)
        self.assertIn(payload["current_state"], set(AlarmState.values))

    def test_alarm_settings_payload_keeps_profile_and_entries_contract(self):
        response = self.client.get(reverse("alarm-settings"))
        self.assertEqual(response.status_code, 200)

        payload = response.json()["data"]
        self.assertIn("profile", payload)
        self.assertIn("entries", payload)

        profile = payload["profile"]
        for key in ("id", "name", "is_active", "created_at", "updated_at"):
            self.assertIn(key, profile)

        entries = payload["entries"]
        self.assertIsInstance(entries, list)
        self.assertGreater(len(entries), 0)

        entries_by_key = {row["key"]: row for row in entries}
        for key in (
            "delay_time",
            "arming_time",
            "trigger_time",
            "code_arm_required",
            "available_arming_states",
            "state_overrides",
        ):
            self.assertIn(key, entries_by_key)
            row = entries_by_key[key]
            for entry_key in ("key", "name", "value_type", "value", "description"):
                self.assertIn(entry_key, row)

    def test_setup_status_payload_keeps_setup_gate_contract(self):
        response = self.client.get(reverse("onboarding-setup-status"))
        self.assertEqual(response.status_code, 200)

        payload = response.json()["data"]
        self.assertIn("onboarding_required", payload)
        self.assertIn("setup_required", payload)
        self.assertIn("requirements", payload)

        requirements = payload["requirements"]
        for key in (
            "has_active_settings_profile",
            "has_alarm_snapshot",
            "has_alarm_code",
            "has_sensors",
            "home_assistant_connected",
        ):
            self.assertIn(key, requirements)
            self.assertIsInstance(requirements[key], bool)
