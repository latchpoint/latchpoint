"""Record what latchpoint wrote to a lock slot, and flag added locks to bring in line (issue #220). Schema only.

  written_pin             the PIN latchpoint last wrote into slot_index,
                          encrypted like DoorCode.encrypted_pin
  written_schedule        the schedule it last wrote there, as
                          lock_push.schedule_fingerprint ("" for none)
  reconcile_requested_at  set when lock sync takes a new PIN or schedule onto
                          a synced code, on each lock added to it, until
                          added_lock_reconcile brings that lock in line

Additive only. All three columns are nullable with no default, so code from
before this migration can still insert assignments after a rollback of the code
alone, and existing rows read as "not known what was written" and "nothing to
reconcile". No backfill: an unknown written PIN on a slot latchpoint pushed is
handled as latchpoint's, so any readable PIN in it other than the code's is
cleared, like every clear did before (lock config slots aside), and an unknown
written schedule gets the slot cleared and pushed again.

The reverse drops the columns. A reconcile still flagged is lost, and the added
lock keeps whatever it has until the import lock changes again or the lock is
removed and added back.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0011_assignment_push_requested"),
    ]

    operations = [
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="written_pin",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="written_schedule",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="doorcodelockassignment",
            name="reconcile_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
