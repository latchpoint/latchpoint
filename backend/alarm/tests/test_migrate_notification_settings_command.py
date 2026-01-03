"""
Tests for the migrate_notification_settings management command.

This command migrates home_assistant_notify settings to rules as part of ADR 0034.
"""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from alarm.models import AlarmSettingsEntry, Rule
from alarm.use_cases.settings_profile import ensure_active_settings_profile


class MigrateNotificationSettingsCommandTests(TestCase):
    def setUp(self):
        self.profile = ensure_active_settings_profile()

    def _set_notify_settings(self, settings: dict):
        """Helper to set notification settings."""
        AlarmSettingsEntry.objects.update_or_create(
            profile=self.profile,
            key="home_assistant_notify",
            defaults={
                "value_type": "json",
                "value": settings,
            },
        )

    def _get_notify_settings(self) -> dict:
        """Helper to get current notification settings."""
        entry = AlarmSettingsEntry.objects.filter(
            profile=self.profile, key="home_assistant_notify"
        ).first()
        return entry.value if entry else {}

    def test_migrates_single_state_to_rule(self):
        """Test that a single state notification setting creates one rule."""
        self._set_notify_settings({
            "enabled": True,
            "service": "notify.mobile_app",
            "cooldown_seconds": 60,
            "states": ["triggered"],
        })

        out = StringIO()
        call_command("migrate_notification_settings", stdout=out)

        # Check rule was created
        rules = Rule.objects.filter(name__startswith="Notify on")
        self.assertEqual(rules.count(), 1)

        rule = rules.first()
        self.assertEqual(rule.name, "Notify on TRIGGERED")
        self.assertEqual(rule.kind, "trigger")
        self.assertTrue(rule.enabled)
        self.assertEqual(rule.cooldown_seconds, 60)

        # Check rule definition
        definition = rule.definition
        self.assertEqual(definition["when"]["op"], "alarm_state_in")
        self.assertEqual(definition["when"]["states"], ["triggered"])
        self.assertEqual(len(definition["then"]), 1)
        self.assertEqual(definition["then"][0]["type"], "ha_call_service")
        self.assertEqual(definition["then"][0]["action"], "notify.mobile_app")
        self.assertIn("message", definition["then"][0]["data"])
        self.assertIn("title", definition["then"][0]["data"])

    def test_migrates_multiple_states_to_rules(self):
        """Test that multiple states create multiple rules."""
        self._set_notify_settings({
            "enabled": True,
            "service": "notify.notify",
            "cooldown_seconds": 30,
            "states": ["triggered", "armed_away", "disarmed"],
        })

        call_command("migrate_notification_settings")

        # Check 3 rules were created
        rules = Rule.objects.filter(name__startswith="Notify on")
        self.assertEqual(rules.count(), 3)

        rule_names = set(rules.values_list("name", flat=True))
        self.assertEqual(
            rule_names,
            {"Notify on TRIGGERED", "Notify on ARMED_AWAY", "Notify on DISARMED"},
        )

    def test_marks_setting_as_migrated(self):
        """Test that the setting is marked as migrated after successful migration."""
        self._set_notify_settings({
            "enabled": True,
            "service": "notify.notify",
            "cooldown_seconds": 0,
            "states": ["triggered"],
        })

        call_command("migrate_notification_settings")

        settings = self._get_notify_settings()
        self.assertTrue(settings.get("migrated"))
        self.assertFalse(settings.get("enabled"))

    def test_skips_if_already_migrated(self):
        """Test that migration is skipped if already marked as migrated."""
        self._set_notify_settings({
            "enabled": True,
            "migrated": True,
            "service": "notify.notify",
            "cooldown_seconds": 0,
            "states": ["triggered"],
        })

        out = StringIO()
        call_command("migrate_notification_settings", stdout=out)

        output = out.getvalue()
        self.assertIn("already been migrated", output)

        # No rules should be created
        rules = Rule.objects.filter(name__startswith="Notify on")
        self.assertEqual(rules.count(), 0)

    def test_force_flag_allows_remigration(self):
        """Test that --force allows re-running migration."""
        self._set_notify_settings({
            "enabled": True,
            "migrated": True,
            "service": "notify.notify",
            "cooldown_seconds": 0,
            "states": ["triggered"],
        })

        call_command("migrate_notification_settings", force=True)

        # Rule should be created despite migrated flag
        rules = Rule.objects.filter(name__startswith="Notify on")
        self.assertEqual(rules.count(), 1)

    def test_skips_if_notifications_disabled(self):
        """Test that migration is skipped if notifications are disabled."""
        self._set_notify_settings({
            "enabled": False,
            "service": "notify.notify",
            "cooldown_seconds": 0,
            "states": ["triggered"],
        })

        out = StringIO()
        call_command("migrate_notification_settings", stdout=out)

        output = out.getvalue()
        self.assertIn("disabled", output)

        # No rules should be created
        rules = Rule.objects.filter(name__startswith="Notify on")
        self.assertEqual(rules.count(), 0)

    def test_skips_if_no_states_configured(self):
        """Test that migration is skipped if no states are configured."""
        self._set_notify_settings({
            "enabled": True,
            "service": "notify.notify",
            "cooldown_seconds": 0,
            "states": [],
        })

        out = StringIO()
        call_command("migrate_notification_settings", stdout=out)

        output = out.getvalue()
        self.assertIn("nothing to migrate", output)

        # No rules should be created
        rules = Rule.objects.filter(name__startswith="Notify on")
        self.assertEqual(rules.count(), 0)

    def test_dry_run_does_not_create_rules(self):
        """Test that --dry-run shows what would be done without making changes."""
        self._set_notify_settings({
            "enabled": True,
            "service": "notify.notify",
            "cooldown_seconds": 0,
            "states": ["triggered", "armed_away"],
        })

        out = StringIO()
        call_command("migrate_notification_settings", dry_run=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Dry run", output)
        self.assertIn("Would create", output)

        # No rules should be created
        rules = Rule.objects.filter(name__startswith="Notify on")
        self.assertEqual(rules.count(), 0)

        # Setting should not be marked as migrated
        settings = self._get_notify_settings()
        self.assertFalse(settings.get("migrated", False))

    def test_uses_default_service_if_not_specified(self):
        """Test that default notify.notify is used if service not specified."""
        self._set_notify_settings({
            "enabled": True,
            "cooldown_seconds": 0,
            "states": ["triggered"],
        })

        call_command("migrate_notification_settings")

        rule = Rule.objects.get(name="Notify on TRIGGERED")
        self.assertEqual(rule.definition["then"][0]["action"], "notify.notify")

    def test_handles_zero_cooldown(self):
        """Test that zero cooldown is stored as None."""
        self._set_notify_settings({
            "enabled": True,
            "service": "notify.notify",
            "cooldown_seconds": 0,
            "states": ["triggered"],
        })

        call_command("migrate_notification_settings")

        rule = Rule.objects.get(name="Notify on TRIGGERED")
        self.assertIsNone(rule.cooldown_seconds)
