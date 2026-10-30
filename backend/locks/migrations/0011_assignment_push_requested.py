"""Add a queued push marker to DoorCodeLockAssignment (issue #124). Schema only.

  push_requested_at  when a save or Retry queued a push of this lock for the
                     push_requested_door_codes task
  push_requested_by  who queued it, the actor on the code_synced event the
                     deferred push records

Additive only. Both columns are nullable with no default, so code from before
this migration can still insert assignments after a rollback of the code alone,
and existing rows read as nothing queued. No backfill.

The reverse drops the columns, which only loses pushes queued in the last few
minutes. The scheduler's 300s retry still picks those locks up as pending.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0010_backfill_assignment_push_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="push_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="push_requested_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
