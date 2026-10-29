"""Mark inactive manual door codes that still hold a slot as pending (issue #158).

Before #144 an inactive code could get its PIN pushed and end up
``is_active=False, push_state=pushed`` with its slot still tracked. Nothing
clears those, since the scheduler only looked at pending codes and Retry
refused inactive ones. Marking them ``pending`` gets them cleared on the next
scheduler tick, and the UI shows them as a pending clear until then.

Data only. Synced codes are left alone (their slots are the lock's own), and so
are ``failed`` codes, which Retry handles. The reverse is a no-op, since putting
them back to ``pushed`` would only strand the PIN on the lock again.
"""

from django.db import migrations


def _mark_pending(apps, schema_editor):
    DoorCode = apps.get_model("locks", "DoorCode")
    DoorCodeLockAssignment = apps.get_model("locks", "DoorCodeLockAssignment")

    holding = DoorCodeLockAssignment.objects.filter(slot_index__isnull=False).values("door_code_id")
    DoorCode.objects.filter(
        source="manual",
        is_active=False,
        push_state="pushed",
        id__in=holding,
    ).update(push_state="pending")


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0006_door_code_push_state"),
    ]

    operations = [
        migrations.RunPython(_mark_pending, migrations.RunPython.noop),
    ]
