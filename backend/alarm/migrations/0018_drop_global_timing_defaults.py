"""Drop the global `arming_time` setting and reset `trigger_time` rows.

Exit delay is now per-state only (lives in `state_overrides`). Before deleting
each profile's global `arming_time`, hoist its value into `state_overrides`
for any armed state that doesn't already have an `arming_time` set, so
profiles that previously relied on the global fallback don't silently lose
their exit delay for un-overridden states.

`trigger_time` default flipped from 600 to 0 (= "stay triggered until manually
disarmed"). Reset stored rows so the new registry default takes over.

Pre-release; no reverse migration.
"""

from __future__ import annotations

from django.db import migrations

ARMED_STATES = ("armed_home", "armed_away", "armed_night", "armed_vacation")


def hoist_global_arming_time_into_overrides(apps, schema_editor):
    """Copy each profile's global `arming_time` into per-state overrides
    for armed states that don't already have an explicit `arming_time`."""
    AlarmSettingsEntry = apps.get_model("alarm", "AlarmSettingsEntry")

    global_rows = AlarmSettingsEntry.objects.filter(key="arming_time").select_related("profile")
    for row in global_rows:
        try:
            global_value = int(row.value)
        except (TypeError, ValueError):
            continue

        overrides_row, _ = AlarmSettingsEntry.objects.get_or_create(
            profile=row.profile,
            key="state_overrides",
            defaults={"value_type": "json", "value": {}},
        )
        overrides = overrides_row.value if isinstance(overrides_row.value, dict) else {}

        changed = False
        for state in ARMED_STATES:
            state_dict = overrides.get(state)
            if not isinstance(state_dict, dict):
                state_dict = {}
                overrides[state] = state_dict
            if "arming_time" not in state_dict:
                state_dict["arming_time"] = global_value
                changed = True

        if changed:
            overrides_row.value = overrides
            overrides_row.value_type = "json"
            overrides_row.save(update_fields=["value", "value_type", "updated_at"])


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
        migrations.RunPython(hoist_global_arming_time_into_overrides, noop),
        migrations.RunPython(drop_orphan_timing_rows, noop),
    ]
