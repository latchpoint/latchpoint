"""Fill in the per-lock push state 0009 added for existing assignments (issues #126, #123). Data only.

  - an assignment with a slot is ``pushed``, with no attempts and no error
  - one with no slot, on an active code that's ``failed``, is ``failed`` and
    gets the code's ``last_push_error``, ``push_attempt_count`` and
    ``last_push_attempt_at``. Which lock failed isn't on record, so every lock
    still without a slot counts, and nothing starts retrying on its own
  - any other one with no slot is ``pending`` with no error and gets the
    code's ``push_attempt_count`` and ``last_push_attempt_at``

``schedule_pending`` stays False everywhere, since nothing before this recorded
a slot whose schedule didn't go out. ``DoorCode.push_state`` isn't touched.

Reverse is a no-op. Nothing reads these columns yet, and 0009's reverse drops them.
"""

from django.db import migrations
from django.db.models import OuterRef, Subquery


def _backfill_assignment_push_state(apps, schema_editor):
    DoorCode = apps.get_model("locks", "DoorCode")
    DoorCodeLockAssignment = apps.get_model("locks", "DoorCodeLockAssignment")

    def code_field(name):
        return Subquery(DoorCode.objects.filter(pk=OuterRef("door_code_id")).values(name)[:1])

    DoorCodeLockAssignment.objects.filter(slot_index__isnull=False).update(
        push_state="pushed",
        push_attempt_count=0,
        last_push_error="",
        schedule_pending=False,
    )

    no_slot = DoorCodeLockAssignment.objects.filter(slot_index__isnull=True)
    failed_code_ids = DoorCode.objects.filter(is_active=True, push_state="failed").values("id")
    no_slot.filter(door_code_id__in=failed_code_ids).update(
        push_state="failed",
        push_attempt_count=code_field("push_attempt_count"),
        last_push_attempt_at=code_field("last_push_attempt_at"),
        last_push_error=code_field("last_push_error"),
        schedule_pending=False,
    )
    no_slot.exclude(door_code_id__in=failed_code_ids).update(
        push_state="pending",
        push_attempt_count=code_field("push_attempt_count"),
        last_push_attempt_at=code_field("last_push_attempt_at"),
        last_push_error="",
        schedule_pending=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0009_assignment_push_state"),
    ]

    operations = [
        migrations.RunPython(_backfill_assignment_push_state, migrations.RunPython.noop),
    ]
