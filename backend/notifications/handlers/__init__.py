"""
Notification handlers registry.

Each handler implements the NotificationHandler protocol for a specific provider.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import NotificationHandler

# Lazy imports to avoid circular dependencies
_HANDLER_CLASSES: dict[str, type["NotificationHandler"]] | None = None


def _load_handlers() -> dict[str, type["NotificationHandler"]]:
    """Load handler classes lazily."""
    from .discord import DiscordHandler
    from .home_assistant import HomeAssistantHandler
    from .pushbullet import PushbulletHandler
    from .slack import SlackHandler
    from .webhook import WebhookHandler

    return {
        "pushbullet": PushbulletHandler,
        "discord": DiscordHandler,
        "home_assistant": HomeAssistantHandler,
        "webhook": WebhookHandler,
        "slack": SlackHandler,
        # TODO: Add more handlers as implemented
        # "telegram": TelegramHandler,
        # "pushover": PushoverHandler,
        # "ntfy": NtfyHandler,
        # "email": EmailHandler,
        # "twilio_sms": TwilioSMSHandler,
        # "twilio_call": TwilioCallHandler,
        # "slack": SlackHandler,
    }


def get_handler(provider_type: str) -> "NotificationHandler":
    """
    Get a handler instance for the given provider type.

    Args:
        provider_type: The type of notification provider

    Returns:
        Handler instance for the provider type

    Raises:
        ValueError: If provider type is unknown
    """
    global _HANDLER_CLASSES
    if _HANDLER_CLASSES is None:
        _HANDLER_CLASSES = _load_handlers()

    handler_class = _HANDLER_CLASSES.get(provider_type)
    if handler_class is None:
        raise ValueError(f"Unknown provider type: {provider_type}")

    return handler_class()


def get_available_provider_types() -> list[str]:
    """Get list of available provider types."""
    global _HANDLER_CLASSES
    if _HANDLER_CLASSES is None:
        _HANDLER_CLASSES = _load_handlers()
    return list(_HANDLER_CLASSES.keys())


def get_handler_metadata(provider_type: str) -> dict:
    """
    Get metadata about a handler for UI display.

    Returns dict with:
        - provider_type: str
        - display_name: str
        - encrypted_fields: list[str]
        - config_schema: dict (JSON Schema)
    """
    handler = get_handler(provider_type)
    return {
        "provider_type": handler.provider_type,
        "display_name": handler.display_name,
        "encrypted_fields": handler.encrypted_fields,
        "config_schema": handler.config_schema,
    }


def get_all_handlers_metadata() -> list[dict]:
    """Get metadata for all available handlers."""
    return [get_handler_metadata(pt) for pt in get_available_provider_types()]
