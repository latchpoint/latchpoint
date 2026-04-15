"""Rename code_hash to encrypted_pin on DoorCode.

Switches door code PIN storage from one-way PBKDF2 hashing to reversible
Fernet encryption (ADR 0083).  Existing hash values are cleared because
they cannot be converted — users re-sync locks or re-create manual codes.
"""

from django.db import migrations, models


def clear_legacy_hashes(apps, schema_editor):
    """Wipe PBKDF2 hashes — they cannot be decrypted into encrypted PINs."""
    DoorCode = apps.get_model("locks", "DoorCode")
    DoorCode.objects.exclude(code_hash=None).update(code_hash=None, pin_length=None)


class Migration(migrations.Migration):
    dependencies = [
        ("locks", "0004_remove_sync_dismissed"),
    ]

    operations = [
        migrations.RunPython(clear_legacy_hashes, migrations.RunPython.noop),
        migrations.RenameField(
            model_name="doorcode",
            old_name="code_hash",
            new_name="encrypted_pin",
        ),
    ]
