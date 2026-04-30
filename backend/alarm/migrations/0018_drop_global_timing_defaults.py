"""Drop the global `arming_time` setting and reset `trigger_time` rows.

Exit delay is now per-state only (lives in `state_overrides`). The global
`arming_time` setting was removed from the registry, so existing rows would
be orphaned — drop them.

`trigger_time` default flipped from 600 to 0 (= "stay triggered until manually
disarmed"). Reset stored rows so the new registry default takes over.

Pre-release; no reverse migration.
"""

from __future__ import annotations

from django.db import migrations


def drop_orphan_timing_rows(apps, schema_editor):
    AlarmSettingsEntry = apps.get_model("alarm", "AlarmSettingsEntry")
    AlarmSettingsEntry.objects.filter(key__in=("arming_time", "trigger_time")).delete()


def noop(apps, schema_editor):
    pass  # data migration — no reverse


class Migration(migrations.Migration):
    dependencies = [
        ("alarm", "0017_rule_stop_group"),
    ]

    operations = [
        migrations.RunPython(drop_orphan_timing_rows, noop),
    ]
