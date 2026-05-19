"""Data migration: rewrite legacy `alarm_trigger { delay_seconds }` actions.

Per ADR-0094, `alarm_trigger` no longer carries its own delay. Existing
rules that authored `{type: "alarm_trigger", delay_seconds: N}` are
rewritten in-place to the composition::

    [
        {"type": "alarm_set_state", "state": "pending"},
        {"type": "alarm_trigger", "delay_seconds": N},
    ]

The executor (ADR-0094 §3.3) handles `delay_seconds` generically by
enqueuing the action through PendingAction; the alarm enters PENDING via
the first action and is forced to TRIGGERED when the delayed second
action fires. The reverse migration collapses the pair back into the
legacy single-action form.
"""

from django.db import migrations


def _is_legacy_delayed_alarm_trigger(action: object) -> bool:
    if not isinstance(action, dict):
        return False
    if action.get("type") != "alarm_trigger":
        return False
    delay = action.get("delay_seconds")
    if isinstance(delay, bool) or not isinstance(delay, int):
        return False
    return delay > 0


def _forward(apps, schema_editor):
    Rule = apps.get_model("alarm", "Rule")
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
            if _is_legacy_delayed_alarm_trigger(action):
                new_then.append({"type": "alarm_set_state", "state": "pending"})
                new_then.append(
                    {"type": "alarm_trigger", "delay_seconds": int(action["delay_seconds"])}
                )
                changed = True
            else:
                new_then.append(action)
        if changed:
            definition["then"] = new_then
            rule.definition = definition
            rule.save(update_fields=["definition", "updated_at"])


def _reverse(apps, schema_editor):
    Rule = apps.get_model("alarm", "Rule")
    for rule in Rule.objects.all():
        definition = rule.definition or {}
        if not isinstance(definition, dict):
            continue
        then = definition.get("then")
        if not isinstance(then, list):
            continue
        changed = False
        new_then: list = []
        i = 0
        while i < len(then):
            action = then[i]
            nxt = then[i + 1] if i + 1 < len(then) else None
            if (
                isinstance(action, dict)
                and action.get("type") == "alarm_set_state"
                and action.get("state") == "pending"
                and isinstance(nxt, dict)
                and nxt.get("type") == "alarm_trigger"
                and isinstance(nxt.get("delay_seconds"), int)
                and not isinstance(nxt.get("delay_seconds"), bool)
                and nxt["delay_seconds"] > 0
            ):
                new_then.append(
                    {"type": "alarm_trigger", "delay_seconds": int(nxt["delay_seconds"])}
                )
                changed = True
                i += 2
                continue
            new_then.append(action)
            i += 1
        if changed:
            definition["then"] = new_then
            rule.definition = definition
            rule.save(update_fields=["definition", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("alarm", "0019_pendingaction")]
    operations = [migrations.RunPython(_forward, _reverse)]
