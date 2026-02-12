from __future__ import annotations

from django.test import TestCase

from alarm.dispatcher.config import DispatcherConfig, get_dispatcher_config, normalize_dispatcher_config
from alarm.models import SystemConfig


class GetDispatcherConfigTests(TestCase):
    """Regression test: get_dispatcher_config must not crash with 'Unknown setting key'."""

    def test_returns_defaults_when_no_db_row(self):
        """get_dispatcher_config should return DispatcherConfig with defaults (no DB row)."""
        config = get_dispatcher_config()
        self.assertIsInstance(config, DispatcherConfig)
        self.assertEqual(config.debounce_ms, 200)

    def test_uses_db_value_when_present(self):
        SystemConfig.objects.create(
            key="dispatcher",
            name="Rule trigger dispatcher",
            value_type="json",
            value={"debounce_ms": 1000, "batch_size_limit": 50},
        )
        config = get_dispatcher_config()
        self.assertEqual(config.debounce_ms, 1000)
        self.assertEqual(config.batch_size_limit, 50)


class NormalizeDispatcherConfigTests(TestCase):
    """Sanity tests for dispatcher config normalization."""

    def test_none_input_returns_defaults(self):
        config = normalize_dispatcher_config(None)
        self.assertEqual(config, DispatcherConfig())

    def test_clamping_debounce_ms(self):
        config = normalize_dispatcher_config({"debounce_ms": 10})
        self.assertEqual(config.debounce_ms, 50)  # minimum is 50

        config = normalize_dispatcher_config({"debounce_ms": 5000})
        self.assertEqual(config.debounce_ms, 2000)  # maximum is 2000
