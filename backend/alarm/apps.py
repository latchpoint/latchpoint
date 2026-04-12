from __future__ import annotations

from django.apps import AppConfig


class AlarmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alarm"

    def ready(self) -> None:
        """Wire websocket/system-status hooks for the alarm app at startup."""
        # Keep `alarm` core free of integration initialization; integrations bind via `alarm.signals`.
        # Core realtime updates are wired here to avoid import side effects at module load time.
        # Configure the in-memory log viewer buffer (ADR 0072)
        import logging

        from django.conf import settings

        # Import tasks to register them with the scheduler
        from . import (
            log_handler,
            receivers,  # noqa: F401
            system_status,  # noqa: F401
            tasks,  # noqa: F401
            ws_signals,  # noqa: F401
        )

        log_handler.configure(
            buffer_size=settings.LOG_VIEWER_BUFFER_SIZE,
            capture_level=getattr(logging, settings.LOG_VIEWER_CAPTURE_LEVEL, logging.DEBUG),
            broadcast_level=getattr(logging, settings.LOG_VIEWER_BROADCAST_LEVEL, logging.WARNING),
        )

        # Verify the encryption key can decrypt existing values (ADR 0079).
        # Deferred to post-migrate to avoid running during migrations.
        from django.db.models.signals import post_migrate

        post_migrate.connect(
            _validate_encryption_key,
            sender=self,
            dispatch_uid="alarm.validate_encryption_key",
        )


def _validate_encryption_key(sender, **kwargs) -> None:  # noqa: ARG001
    """Spot-check one encrypted value to verify the key is correct.

    Prevents silent data loss from key rotation or misconfiguration.
    Only runs if there are already encrypted values in the database.
    """
    import logging

    from alarm.crypto import ENCRYPTED_PREFIX, SettingsEncryption
    from alarm.models import AlarmSettingsEntry
    from alarm.settings_registry import ALARM_PROFILE_SETTINGS

    logger = logging.getLogger("alarm.crypto")

    keys_with_secrets = [s.key for s in ALARM_PROFILE_SETTINGS if s.encrypted_fields]
    if not keys_with_secrets:
        return

    for entry in AlarmSettingsEntry.objects.filter(key__in=keys_with_secrets).iterator():
        if not isinstance(entry.value, dict):
            continue
        for v in entry.value.values():
            if isinstance(v, str) and v.startswith(ENCRYPTED_PREFIX):
                try:
                    crypto = SettingsEncryption.get()
                    crypto.decrypt(v)
                    logger.debug("Encryption key validated successfully.")
                    return  # Key works — one successful decrypt is enough
                except Exception:
                    raise RuntimeError(
                        "SETTINGS_ENCRYPTION_KEY cannot decrypt existing values. "
                        "The key may have been rotated or lost. "
                        "Restore the original key or re-configure credentials."
                    ) from None
