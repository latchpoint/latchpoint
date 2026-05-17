from __future__ import annotations

from django.db import migrations

DEFAULT_INSTANCE_ID = "default"


def consolidate_instance_id(apps, schema_editor):
    """
    Collapse pre-existing `(task_name, instance_id)` rows down to one row per
    task and rewrite the instance id to the stable default. See ADR-0093.
    """
    SchedulerTaskHealth = apps.get_model("scheduler", "SchedulerTaskHealth")
    SchedulerTaskRun = apps.get_model("scheduler", "SchedulerTaskRun")

    # Pick a survivor per task: most recent by last_finished_at, falling back
    # to last_heartbeat_at then updated_at. NULLs sort last under DESC.
    survivors: set[int] = set()
    seen: set[str] = set()
    rows = SchedulerTaskHealth.objects.all().order_by(
        "task_name",
        "-last_finished_at",
        "-last_heartbeat_at",
        "-updated_at",
    )
    for row in rows:
        if row.task_name in seen:
            continue
        seen.add(row.task_name)
        survivors.add(row.pk)

    # Drop losers before mutating the unique-keyed survivor.
    SchedulerTaskHealth.objects.exclude(pk__in=survivors).delete()
    SchedulerTaskHealth.objects.filter(pk__in=survivors).update(
        instance_id=DEFAULT_INSTANCE_ID
    )

    # Run history has no unique constraint; rewrite in bulk.
    SchedulerTaskRun.objects.update(instance_id=DEFAULT_INSTANCE_ID)


def reverse_noop(apps, schema_editor):
    # Prior hostname:pid values are unrecoverable; reverse is a no-op so a
    # future rollback past this point can proceed without raising.
    pass


class Migration(migrations.Migration):
    dependencies = [
        (
            "scheduler",
            "0002_rename_scheduler_ta_task_na_99a1a7_idx_scheduler_s_task_na_f7effb_idx_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(consolidate_instance_id, reverse_noop),
    ]
