from __future__ import annotations

from rest_framework.exceptions import ValidationError

from alarm.models import SystemConfig
from alarm.settings_registry import SYSTEM_CONFIG_SETTINGS, SYSTEM_CONFIG_SETTINGS_BY_KEY


def ensure_system_config_defaults() -> None:
    """Ensure all registered system config keys exist with their default metadata/value."""
    for definition in SYSTEM_CONFIG_SETTINGS:
        SystemConfig.objects.update_or_create(
            key=definition.key,
            defaults={
                "name": definition.name,
                "value_type": definition.value_type,
                "value": definition.default,
                "description": definition.description,
            },
        )


def list_system_config():
    """Return all system config rows, ensuring defaults are present first."""
    ensure_system_config_defaults()
    return SystemConfig.objects.all()


def update_system_config(*, row: SystemConfig, changes: dict, actor_user) -> SystemConfig:
    """Apply updates to a system config row (value/description) and track who modified it."""
    definition = SYSTEM_CONFIG_SETTINGS_BY_KEY.get(row.key)
    if not definition:
        raise ValidationError({"detail": "Unknown system config key."})

    if "value" in changes:
        row.value = changes["value"]
    if "description" in changes:
        row.description = changes["description"] or ""
    row.modified_by = actor_user
    row.save(update_fields=["value", "description", "modified_by", "updated_at"])
    return row
