"""
Management command to migrate notification settings to rules.

This command converts existing home_assistant_notify settings into rules
as part of ADR 0034 - Notifications as Rule Actions.

For each alarm state in the notification settings, it creates a corresponding
rule with:
- Name: "Notify on {state}"
- Kind: trigger
- Condition: alarm_state_in with the specific state
- Action: ha_call_service with notify.*
- Cooldown: from the original setting

Usage:
    python manage.py migrate_notification_settings
    python manage.py migrate_notification_settings --dry-run
    python manage.py migrate_notification_settings --force
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from alarm.models import Rule, AlarmSettingsEntry
from alarm.state_machine.settings import get_active_settings_profile


class Command(BaseCommand):
    help = "Migrate home_assistant_notify settings to rules (ADR 0034)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force migration even if already migrated",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        profile = get_active_settings_profile()
        # Read directly from database since setting was removed from registry
        entry = AlarmSettingsEntry.objects.filter(
            profile=profile, key="home_assistant_notify"
        ).first()
        notify_settings = entry.value if entry else {}

        # Check if already migrated (unless --force)
        if notify_settings.get("migrated") and not force:
            self.stdout.write(
                self.style.WARNING(
                    "Notification settings have already been migrated. "
                    "Use --force to migrate again."
                )
            )
            return

        # Check if notifications are enabled
        if not notify_settings.get("enabled"):
            self.stdout.write(
                self.style.SUCCESS(
                    "Notifications are disabled - nothing to migrate."
                )
            )
            return

        states = notify_settings.get("states", [])
        if not states:
            self.stdout.write(
                self.style.SUCCESS(
                    "No alarm states configured for notifications - nothing to migrate."
                )
            )
            return

        service = notify_settings.get("service", "notify.notify")
        cooldown_seconds = notify_settings.get("cooldown_seconds", 0)

        # Get or create a system user for migration
        system_user = self._get_system_user()

        rules_to_create = []
        for state in states:
            rule_name = f"Notify on {state.upper()}"
            rule_definition = {
                "when": {"op": "alarm_state_in", "states": [state]},
                "then": [
                    {
                        "type": "ha_call_service",
                        "action": service,
                        "data": {
                            "message": f"Alarm is now {state}",
                            "title": "Alarm Notification",
                        },
                    }
                ],
            }

            rules_to_create.append({
                "name": rule_name,
                "kind": "trigger",
                "enabled": True,
                "priority": 0,
                "schema_version": 1,
                "definition": rule_definition,
                "cooldown_seconds": cooldown_seconds if cooldown_seconds > 0 else None,
                "created_by": system_user,
            })

            if dry_run:
                self.stdout.write(f"  Would create rule: {rule_name}")
                self.stdout.write(f"    Service: {service}")
                self.stdout.write(f"    State: {state}")
                self.stdout.write(f"    Cooldown: {cooldown_seconds}s")
            else:
                self.stdout.write(f"  Creating rule: {rule_name}")

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDry run complete. Would create {len(rules_to_create)} rules."
                )
            )
            return

        # Create rules and mark as migrated atomically
        with transaction.atomic():
            for rule_data in rules_to_create:
                Rule.objects.create(**rule_data)

            # Mark the setting as migrated
            updated_settings = {**notify_settings, "migrated": True, "enabled": False}
            AlarmSettingsEntry.objects.update_or_create(
                profile=profile,
                key="home_assistant_notify",
                defaults={
                    "value_type": "json",
                    "value": updated_settings,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nMigration complete. Created {len(rules_to_create)} rules "
                "and marked notification settings as migrated."
            )
        )
        self.stdout.write(
            self.style.NOTICE(
                "Note: The old notification settings have been disabled. "
                "Notifications will now be sent via the newly created rules."
            )
        )

    def _get_system_user(self) -> User:
        """Get or create a system user for the migration."""
        user, _ = User.objects.get_or_create(
            email="system@localhost",
            defaults={
                "is_active": True,
            },
        )
        return user
