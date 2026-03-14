"""
Auto-provisioning of notification providers from environment variables.

For each handler type whose ``is_enabled_from_env()`` returns ``True``, ensures
a corresponding ``NotificationProvider`` row exists in the given profile.  The
``config`` field is left empty — all provider configuration (including secrets)
is read from env at dispatch time via ``handler.from_env()``.  Idempotent:
updates existing rows if found, creates new ones otherwise.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# List of provider type strings to check for env-based auto-provisioning.
_PROVIDER_TYPES = [
    "pushbullet",
    "discord",
    "slack",
    "webhook",
    "home_assistant",
]


def ensure_env_providers_exist(profile) -> None:
    """Create or update ``NotificationProvider`` rows for env-enabled providers."""
    from .handlers import get_handler
    from .models import NotificationProvider

    for provider_type in _PROVIDER_TYPES:
        handler = get_handler(provider_type)

        if not hasattr(handler, "is_enabled_from_env"):
            continue

        enabled = handler.is_enabled_from_env()

        # Use a deterministic name keyed on display_name to avoid collisions
        # with user-created providers and ensure idempotent get_or_create.
        env_name = f"{handler.display_name} (env)"

        if enabled:
            obj, created = NotificationProvider.objects.get_or_create(
                profile=profile,
                name=env_name,
                defaults={
                    "provider_type": provider_type,
                    "config": {},
                    "is_enabled": True,
                },
            )
            if created:
                logger.info("Created %s provider from env", provider_type)
            else:
                update_fields = []
                if obj.provider_type != provider_type:
                    old_type = obj.provider_type
                    obj.provider_type = provider_type
                    update_fields.append("provider_type")
                    logger.warning(
                        "Corrected provider_type for '%s' from %s to %s",
                        env_name,
                        old_type,
                        provider_type,
                    )
                if not obj.is_enabled:
                    obj.is_enabled = True
                    update_fields.append("is_enabled")
                if update_fields:
                    update_fields.append("updated_at")
                    obj.save(update_fields=update_fields)
                    logger.info("Updated existing %s provider from env", provider_type)
        else:
            updated = NotificationProvider.objects.filter(
                profile=profile,
                name=env_name,
                is_enabled=True,
            ).update(is_enabled=False)
            if updated:
                logger.info("Disabled %s provider (env disabled)", provider_type)
