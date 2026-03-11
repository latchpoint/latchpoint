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

# Provider type strings to check for env-based auto-provisioning.
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

        existing = NotificationProvider.objects.filter(
            profile=profile,
            provider_type=provider_type,
        ).first()

        if enabled:
            if existing:
                if not existing.is_enabled:
                    existing.is_enabled = True
                    existing.save(update_fields=["is_enabled", "updated_at"])
                    logger.info("Enabled existing %s provider from env", provider_type)
            else:
                # Use a deterministic name that includes provider_type to avoid
                # collisions with the unique_together("profile", "name") constraint
                # in case a user-created provider already uses the display_name.
                env_name = f"{handler.display_name} (env)"
                NotificationProvider.objects.create(
                    profile=profile,
                    name=env_name,
                    provider_type=provider_type,
                    config={},
                    is_enabled=True,
                )
                logger.info("Created %s provider from env", provider_type)
        elif existing and existing.is_enabled:
            existing.is_enabled = False
            existing.save(update_fields=["is_enabled", "updated_at"])
            logger.info("Disabled %s provider (env disabled)", provider_type)
