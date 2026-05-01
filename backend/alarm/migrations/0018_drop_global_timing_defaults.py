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
    """Remove rows that should fall back to the new registry defaults.

    `arming_time` is no longer a global setting (per-state only via
    `state_overrides`), so every row is dropped — the hoist step above
    already copied the value into the overrides so nothing is lost.

    `trigger_time`'s default flipped from 600 to 0; only delete rows that
    still hold the prior default, so user-customized values (e.g. 300, 900)
    survive the migration instead of silently snapping to 0.
    """
    AlarmSettingsEntry = apps.get_model("alarm", "AlarmSettingsEntry")

    AlarmSettingsEntry.objects.filter(key="arming_time").delete()

    # `value` is a JSONField, so the old default may be stored as either the
    # numeric literal `600` or the JSON string `"600"`. Match both in one
    # bulk DELETE rather than looping per row.
    old_trigger_time_default = 600
    AlarmSettingsEntry.objects.filter(
        key="trigger_time",
        value__in=[old_trigger_time_default, str(old_trigger_time_default)],
    ).delete()


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
