"""
Auto-provisioning of notification providers from environment variables.

For each handler type whose ``is_enabled_from_env()`` returns ``True``, ensures
a corresponding ``NotificationProvider`` row exists in the given profile. Config
field stores only non-secret display fields — secrets are read from env at
dispatch time via ``handler.from_env()``.  Idempotent: updates existing rows
if found, creates new ones otherwise.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Map of provider_type -> (handler_class_path, display_name)
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
                NotificationProvider.objects.create(
                    profile=profile,
                    name=handler.display_name,
                    provider_type=provider_type,
                    config={},
                    is_enabled=True,
                )
                logger.info("Created %s provider from env", provider_type)
        elif existing and existing.is_enabled:
            existing.is_enabled = False
            existing.save(update_fields=["is_enabled", "updated_at"])
            logger.info("Disabled %s provider (env disabled)", provider_type)
