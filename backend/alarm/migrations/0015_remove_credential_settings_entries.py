"""Data migration: remove credential-bearing AlarmSettingsEntry rows and clear NotificationProvider.config.

ADR 0075 moved integration credentials to env vars. These DB rows are no longer read;
this migration removes stale encrypted data.
"""

from __future__ import annotations

from django.db import migrations

CREDENTIAL_KEYS = ("home_assistant_connection", "mqtt_connection", "zwavejs_connection")


def remove_credential_entries(apps, schema_editor):
    AlarmSettingsEntry = apps.get_model("alarm", "AlarmSettingsEntry")
    AlarmSettingsEntry.objects.filter(key__in=CREDENTIAL_KEYS).delete()

    NotificationProvider = apps.get_model("notifications", "NotificationProvider")
    NotificationProvider.objects.all().update(config={})


def noop(apps, schema_editor):
    pass  # data migration — no reverse


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0014_alter_alarmevent_event_type_choices"),
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(remove_credential_entries, noop),
    ]
