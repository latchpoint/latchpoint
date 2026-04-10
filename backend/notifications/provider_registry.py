"""
Auto-provisioning of notification providers from environment variables.

For each handler type whose ``is_configured_from_env()`` returns ``True``,
ensures a corresponding ``NotificationProvider`` row exists in the given profile.
The ``config`` field is left empty — all provider configuration (including
secrets) is read from env at dispatch time via ``handler.from_env()``.

The ``is_enabled`` flag is **not** managed here — it is controlled exclusively
via the UI toggle (ADR 0078).  Providers are created with ``is_enabled=False``
and must be enabled by an admin through the settings UI.
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
    """Create ``NotificationProvider`` rows for env-configured providers (idempotent).

    Existing rows are never modified — ``is_enabled`` is managed by the UI only.
    """
    from .handlers import get_handler
    from .models import NotificationProvider

    for provider_type in _PROVIDER_TYPES:
        handler = get_handler(provider_type)

        if not hasattr(handler, "is_configured_from_env"):
            continue

        configured = handler.is_configured_from_env()

        # Use a deterministic name keyed on display_name to avoid collisions
        # with user-created providers and ensure idempotent get_or_create.
        env_name = f"{handler.display_name} (env)"

        if configured:
            obj, created = NotificationProvider.objects.get_or_create(
                profile=profile,
                name=env_name,
                defaults={
                    "provider_type": provider_type,
                    "config": {},
                    "is_enabled": False,
                },
            )
            if created:
                logger.info("Created %s provider from env (disabled by default)", provider_type)
            elif obj.provider_type != provider_type:
                old_type = obj.provider_type
                obj.provider_type = provider_type
                obj.save(update_fields=["provider_type", "updated_at"])
                logger.warning(
                    "Corrected provider_type for '%s' from %s to %s",
                    env_name,
                    old_type,
                    provider_type,
                )
