"""Add push_state, last_push_attempt_at, last_push_error to DoorCode (ADR 0092).

Tracks the lifecycle of programming a PIN onto a physical lock:
  pending → push not yet attempted (or queued for retry)
  pushed  → last push succeeded; the lock holds the current PIN + schedule
  failed  → push hit the configured retry cap (permanent error / N attempts)

Backfill:
  - Synced codes → pushed (the lock is authoritative).
  - Manual codes with any assignment carrying a non-NULL slot_index → pushed.
  - Everything else stays at the default (pending).
"""

from django.db import migrations, models


def _backfill_push_state(apps, schema_editor):
    """Mark already-on-lock codes as pushed so the scheduler doesn't re-push them."""
    DoorCode = apps.get_model("locks", "DoorCode")
    DoorCodeLockAssignment = apps.get_model("locks", "DoorCodeLockAssignment")

    DoorCode.objects.filter(source="synced").update(push_state="pushed")

    manual_code_ids = (
        DoorCodeLockAssignment.objects.filter(slot_index__isnull=False)
        .values_list("door_code_id", flat=True)
        .distinct()
    )
    DoorCode.objects.filter(source="manual", id__in=list(manual_code_ids)).update(push_state="pushed")


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0005_rename_code_hash_to_encrypted_pin"),
    ]

    operations = [
        migrations.AddField(
            model_name="doorcode",
            name="push_state",
            field=models.CharField(
                choices=[("pending", "Pending"), ("pushed", "Pushed"), ("failed", "Failed")],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="doorcode",
            name="push_attempt_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="doorcode",
            name="last_push_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doorcode",
            name="last_push_error",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.RunPython(_backfill_push_state, migrations.RunPython.noop),
    ]
