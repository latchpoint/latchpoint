from __future__ import annotations

import logging

from alarm.models import SystemConfig
from alarm.settings_registry import SYSTEM_CONFIG_SETTINGS_BY_KEY

logger = logging.getLogger(__name__)


def get_int_system_config_value(*, key: str) -> int:
    """
    Read a SystemConfig key as an int, falling back to the registry default.

    Logs a warning and returns default if the row is missing or not parseable.
    """
    default = SYSTEM_CONFIG_SETTINGS_BY_KEY[key].default

    try:
        row = SystemConfig.objects.get(key=key)
        return int(row.value)
    except SystemConfig.DoesNotExist:
        return default
    except (TypeError, ValueError):
        logger.warning("Invalid %s value, using default %d", key, default)
        return default

