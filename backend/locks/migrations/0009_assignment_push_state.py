"""Add per-lock push state columns to DoorCodeLockAssignment (issues #126, #123). Schema only.

  push_state            pending / pushed / failed, same choices as DoorCode.push_state
  push_attempt_count    consecutive failed pushes to this lock
  last_push_attempt_at  when this lock was last pushed to
  last_push_error       this lock's last push error
  schedule_pending      the PIN is in the slot but its CC 78 schedule isn't yet

Additive only. Every NOT NULL column gets ``db_default`` as well as ``default``,
so the database fills it in for an INSERT that leaves it out. Code from before
this migration doesn't know these columns, so after a rollback of the code
alone it can still create assignments.

0010 fills the columns in for existing rows. The reverse drops the columns.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0008_backfill_synced_code_push_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="push_state",
            field=models.CharField(
                choices=[("pending", "Pending"), ("pushed", "Pushed"), ("failed", "Failed")],
                db_default="pending",
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="push_attempt_count",
            field=models.PositiveIntegerField(db_default=0, default=0),
        ),
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="last_push_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="last_push_error",
            field=models.CharField(blank=True, db_default="", default="", max_length=500),
        ),
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="schedule_pending",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
