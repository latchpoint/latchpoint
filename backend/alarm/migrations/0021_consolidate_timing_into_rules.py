"""Data + schema migration: consolidate timing config into rules (ADR-0095).

Forward operations:

1. For each ``Rule`` with an ``alarm_arm`` action in ``definition.then``,
   copy the active profile's ``state_overrides[<mode>].arming_time`` into
   the action as ``arming_time_seconds`` (when > 0).

2. For each profile with ``disarm_after_trigger=true`` AND
   ``trigger_time > 0``, create a ``disarm``-kind rule that fires when
   the alarm has been TRIGGERED for ``trigger_time`` seconds. This
   preserves the prior auto-disarm-after-trigger behavior as an explicit
   rule.

3. Delete the four obsolete ``AlarmSettingsEntry`` rows
   (``delay_time``, ``trigger_time``, ``state_overrides``,
   ``disarm_after_trigger``) from every profile.

4. Drop ``AlarmStateSnapshot.timing_snapshot`` and
   ``Sensor.is_entry_point`` model fields.

Reverse operations re-add the model fields and best-effort re-derive
the four entries on the active profile from any ``arming_time_seconds``
values present on ``alarm_arm`` actions. The auto-generated disarm
rule is left intact on rollback (lossy; users may delete it manually).
"""

from django.db import migrations, models


ARMED_MODES = ("armed_home", "armed_away", "armed_night", "armed_vacation")


def _forward(apps, schema_editor):
    Rule = apps.get_model("alarm", "Rule")
    AlarmSettingsProfile = apps.get_model("alarm", "AlarmSettingsProfile")
    AlarmSettingsEntry = apps.get_model("alarm", "AlarmSettingsEntry")

    active_profile = AlarmSettingsProfile.objects.filter(is_active=True).first()

    state_overrides: dict = {}
    if active_profile is not None:
        entry = AlarmSettingsEntry.objects.filter(profile=active_profile, key="state_overrides").first()
        if entry and isinstance(entry.value, dict):
            state_overrides = entry.value

    # 1) Stamp arming_time_seconds onto each alarm_arm action.
    for rule in Rule.objects.all():
        definition = rule.definition or {}
        if not isinstance(definition, dict):
            continue
        then = definition.get("then")
        if not isinstance(then, list):
            continue

        changed = False
        new_then: list = []
        for action in then:
            if isinstance(action, dict) and action.get("type") == "alarm_arm":
                mode = action.get("mode")
                if isinstance(mode, str) and mode in ARMED_MODES and "arming_time_seconds" not in action:
                    override = state_overrides.get(mode) if isinstance(state_overrides, dict) else None
                    if isinstance(override, dict):
                        arming_time = override.get("arming_time")
                        if isinstance(arming_time, int) and not isinstance(arming_time, bool) and arming_time > 0:
                            action = {**action, "arming_time_seconds": int(arming_time)}
                            changed = True
            new_then.append(action)
        if changed:
            definition["then"] = new_then
            rule.definition = definition
            rule.save(update_fields=["definition", "updated_at"])

    # 2) Generate a disarm-kind rule for profiles with auto-disarm-after-trigger.
    for profile in AlarmSettingsProfile.objects.all():
        disarm_entry = AlarmSettingsEntry.objects.filter(profile=profile, key="disarm_after_trigger").first()
        trigger_entry = AlarmSettingsEntry.objects.filter(profile=profile, key="trigger_time").first()
        if not disarm_entry or not bool(disarm_entry.value):
            continue
        if not trigger_entry or not isinstance(trigger_entry.value, int) or trigger_entry.value <= 0:
            continue
        # Only attach the rule when this is the active profile; rules aren't
        # profile-scoped, so generating one per profile would create
        # duplicates that all fire whenever the alarm is TRIGGERED.
        if not profile.is_active:
            continue

        rule_name = f"Auto-disarm after trigger ({profile.name})"
        if Rule.objects.filter(name=rule_name, kind="disarm").exists():
            continue

        Rule.objects.create(
            name=rule_name,
            kind="disarm",
            enabled=True,
            priority=10,
            stop_processing=False,
            stop_group="",
            schema_version=1,
            definition={
                "when": {
                    "op": "for",
                    "seconds": int(trigger_entry.value),
                    "child": {"op": "alarm_state_in", "states": ["triggered"]},
                },
                "then": [{"type": "alarm_disarm"}],
            },
        )

    # 3) Delete the obsolete settings entries from every profile.
    AlarmSettingsEntry.objects.filter(
        key__in=["delay_time", "trigger_time", "state_overrides", "disarm_after_trigger"]
    ).delete()


def _reverse(apps, schema_editor):
    Rule = apps.get_model("alarm", "Rule")
    AlarmSettingsProfile = apps.get_model("alarm", "AlarmSettingsProfile")
    AlarmSettingsEntry = apps.get_model("alarm", "AlarmSettingsEntry")

    active_profile = AlarmSettingsProfile.objects.filter(is_active=True).first()
    if active_profile is None:
        return

    # Re-derive state_overrides from any arming_time_seconds values still on alarm_arm actions.
    derived_overrides: dict = {}
    for rule in Rule.objects.all():
        definition = rule.definition or {}
        if not isinstance(definition, dict):
            continue
        then = definition.get("then")
        if not isinstance(then, list):
            continue
        for action in then:
            if not isinstance(action, dict):
                continue
            if action.get("type") != "alarm_arm":
                continue
            mode = action.get("mode")
            seconds = action.get("arming_time_seconds")
            if (
                isinstance(mode, str)
                and mode in ARMED_MODES
                and isinstance(seconds, int)
                and not isinstance(seconds, bool)
                and seconds > 0
            ):
                derived_overrides.setdefault(mode, {"arming_time": seconds})

    # Re-add the four entries with their registry defaults (state_overrides uses derived values).
    defaults = {
        "delay_time": 60,
        "trigger_time": 0,
        "disarm_after_trigger": False,
        "state_overrides": derived_overrides
        or {
            "armed_home": {"arming_time": 0},
            "armed_night": {"arming_time": 10},
            "armed_away": {"arming_time": 60},
            "armed_vacation": {"arming_time": 60},
        },
    }
    value_types = {
        "delay_time": "integer",
        "trigger_time": "integer",
        "disarm_after_trigger": "boolean",
        "state_overrides": "json",
    }
    for key, value in defaults.items():
        AlarmSettingsEntry.objects.update_or_create(
            profile=active_profile,
            key=key,
            defaults={"value": value, "value_type": value_types[key]},
        )


class Migration(migrations.Migration):
    dependencies = [("alarm", "0020_rewrite_delayed_alarm_trigger")]

    operations = [
        migrations.RunPython(_forward, _reverse),
        migrations.RemoveField(
            model_name="alarmstatesnapshot",
            name="timing_snapshot",
        ),
        migrations.RemoveField(
            model_name="sensor",
            name="is_entry_point",
        ),
    ]
