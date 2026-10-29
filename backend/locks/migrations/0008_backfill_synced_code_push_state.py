"""Mark active synced door codes that hold a slot as pushed (issue #149). Data only, no schema change.

Lock config sync created synced codes without setting ``push_state``, so every
code it imported after 0006 got the model default ``pending`` and kept it. A
synced code is read off the lock, so one that still holds a slot is on it.

Left as they are:
  - inactive synced codes
  - synced codes with no tracked slot
  - synced codes with any ``clear_failed`` or ``push_unconfirmed`` event, since
    a slot of theirs may hold an older PIN (#111, #144) and those codes must not
    show ``pushed`` until it's settled

Reverse is a no-op: nothing records which rows were pending before, and
putting a synced code back to pending only brings the bug back.
"""

from django.db import migrations
from django.db.models import Exists, OuterRef


def _backfill_synced_push_state(apps, schema_editor):
    DoorCode = apps.get_model("locks", "DoorCode")
    DoorCodeLockAssignment = apps.get_model("locks", "DoorCodeLockAssignment")
    DoorCodeEvent = apps.get_model("locks", "DoorCodeEvent")

    holds_slot = DoorCodeLockAssignment.objects.filter(door_code=OuterRef("pk"), slot_index__isnull=False)
    slot_cleanup_on_record = DoorCodeEvent.objects.filter(
        door_code=OuterRef("pk"),
        event_type="code_failed",
        metadata__action__in=["clear_failed", "push_unconfirmed"],
    )
    (
        DoorCode.objects.filter(source="synced", push_state="pending", is_active=True)
        .filter(Exists(holds_slot))
        .exclude(Exists(slot_cleanup_on_record))
        .update(push_state="pushed", last_push_error="", push_attempt_count=0)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0007_pending_inactive_door_codes_holding_slots"),
    ]

    operations = [
        migrations.RunPython(_backfill_synced_push_state, migrations.RunPython.noop),
    ]
