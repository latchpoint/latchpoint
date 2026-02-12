from __future__ import annotations

from django.test import TestCase

from alarm.models import SystemConfig
from alarm.settings_registry import SYSTEM_CONFIG_SETTINGS_BY_KEY
from alarm.state_machine.errors import TransitionError
from alarm.state_machine.settings import get_system_config_value


class GetSystemConfigValueTests(TestCase):
    """Regression tests for get_system_config_value (Bug 2 & Bug 3)."""

    def test_returns_registry_default_when_no_db_row(self):
        """When no SystemConfig row exists, the registry default should be returned."""
        definition = SYSTEM_CONFIG_SETTINGS_BY_KEY["dispatcher"]
        result = get_system_config_value("dispatcher")
        self.assertEqual(result, definition.default)

    def test_returns_db_value_when_row_exists(self):
        """When a SystemConfig row exists, its value should be returned."""
        custom = {"debounce_ms": 500, "batch_size_limit": 50}
        SystemConfig.objects.create(
            key="dispatcher",
            name="Rule trigger dispatcher",
            value_type="json",
            value=custom,
        )
        result = get_system_config_value("dispatcher")
        self.assertEqual(result, custom)

    def test_raises_for_unknown_key(self):
        """An unregistered key should raise TransitionError, not silently return None."""
        with self.assertRaises(TransitionError):
            get_system_config_value("totally_unknown_key")

    def test_integer_system_config_key(self):
        """Verify it works for non-JSON system config keys like retention days."""
        result = get_system_config_value("events.retention_days")
        self.assertEqual(result, 30)  # registry default
