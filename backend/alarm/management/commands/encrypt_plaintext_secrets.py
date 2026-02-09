from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from alarm.crypto import ENCRYPTION_PREFIX, can_encrypt, encrypt_secret
from alarm.models import AlarmSettingsEntry


# Settings keys with encrypted fields.
_KEY_ENCRYPTED_FIELDS: dict[str, list[str]] = {
    "mqtt_connection": ["password"],
    "zwavejs_connection": ["api_token"],
    "home_assistant_connection": ["token"],
}


class Command(BaseCommand):
    help = "Re-encrypt any AlarmSettingsEntry values that contain plaintext secrets (missing enc: prefix)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be re-encrypted without making changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if not can_encrypt():
            raise CommandError(
                "Encryption is not configured. Set SETTINGS_ENCRYPTION_KEY before running this command."
            )

        total_fixed = 0
        for key, fields in _KEY_ENCRYPTED_FIELDS.items():
            entries = AlarmSettingsEntry.objects.filter(key=key)
            for entry in entries:
                value = entry.value
                if not isinstance(value, dict):
                    continue
                changed = False
                for field in fields:
                    raw = value.get(field)
                    if not isinstance(raw, str) or not raw:
                        continue
                    if raw.startswith(ENCRYPTION_PREFIX):
                        continue
                    # Plaintext secret found — re-encrypt it.
                    if dry_run:
                        self.stdout.write(
                            f"  [dry-run] Would re-encrypt {key}.{field} "
                            f"(profile_id={entry.profile_id})"
                        )
                    else:
                        value[field] = encrypt_secret(raw)
                        changed = True
                    total_fixed += 1
                if changed:
                    entry.value = value
                    entry.save(update_fields=["value"])

        prefix = "[dry-run] " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"{prefix}Done. {total_fixed} secret(s) re-encrypted."))
