"""Remove the sync_dismissed concept from door code lock assignments.

Dismissed slots were a soft-delete mechanism for synced door codes. Now that
deletion hard-deletes the DB record after clearing the physical lock slot
(commit 7a65374), the dismissed state is unnecessary.

This migration cleans up any leftover dismissed records before dropping the
column.
"""

from django.db import migrations


def cleanup_dismissed_records(apps, schema_editor):
    """Delete dismissed assignments and their orphaned DoorCode parents."""
    DoorCodeLockAssignment = apps.get_model("locks", "DoorCodeLockAssignment")
    DoorCode = apps.get_model("locks", "DoorCode")

    dismissed = DoorCodeLockAssignment.objects.filter(sync_dismissed=True)
    door_code_ids = set(dismissed.values_list("door_code_id", flat=True))
    dismissed.delete()

    # Delete orphaned DoorCode records that no longer have any assignments.
    for code_id in door_code_ids:
        if not DoorCodeLockAssignment.objects.filter(door_code_id=code_id).exists():
            DoorCode.objects.filter(id=code_id).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0003_lock_config_sync_fields"),
    ]

    operations = [
        migrations.RunPython(cleanup_dismissed_records, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="doorcodelockassignment",
            name="sync_dismissed",
        ),
    ]
