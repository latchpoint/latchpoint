from __future__ import annotations

from django.test import SimpleTestCase

from integrations_zigbee2mqtt.config import (
    DEFAULT_SETTINGS,
    mask_zigbee2mqtt_settings,
    normalize_zigbee2mqtt_settings,
)


class NormalizeZigbee2mqttSettingsRunRulesTests(SimpleTestCase):
    """Regression tests for run_rules_* fields on Zigbee2mqttSettings (Bug 1)."""

    def test_defaults_applied_when_fields_missing(self):
        """normalize should populate run_rules_* defaults from an empty dict."""
        settings = normalize_zigbee2mqtt_settings({})
        self.assertFalse(settings.run_rules_on_event)
        self.assertEqual(settings.run_rules_debounce_seconds, DEFAULT_SETTINGS["run_rules_debounce_seconds"])
        self.assertEqual(settings.run_rules_max_per_minute, DEFAULT_SETTINGS["run_rules_max_per_minute"])
        self.assertEqual(settings.run_rules_kinds, [])

    def test_explicit_values_are_preserved(self):
        raw = {
            "run_rules_on_event": True,
            "run_rules_debounce_seconds": 10,
            "run_rules_max_per_minute": 120,
            "run_rules_kinds": ["trigger", "state_change"],
        }
        settings = normalize_zigbee2mqtt_settings(raw)
        self.assertTrue(settings.run_rules_on_event)
        self.assertEqual(settings.run_rules_debounce_seconds, 10)
        self.assertEqual(settings.run_rules_max_per_minute, 120)
        self.assertEqual(settings.run_rules_kinds, ["trigger", "state_change"])

    def test_invalid_debounce_falls_back_to_default(self):
        settings = normalize_zigbee2mqtt_settings({"run_rules_debounce_seconds": "bad"})
        self.assertEqual(settings.run_rules_debounce_seconds, DEFAULT_SETTINGS["run_rules_debounce_seconds"])

    def test_negative_debounce_falls_back_to_default(self):
        settings = normalize_zigbee2mqtt_settings({"run_rules_debounce_seconds": -1})
        self.assertEqual(settings.run_rules_debounce_seconds, DEFAULT_SETTINGS["run_rules_debounce_seconds"])

    def test_invalid_max_per_minute_falls_back_to_default(self):
        settings = normalize_zigbee2mqtt_settings({"run_rules_max_per_minute": 0})
        self.assertEqual(settings.run_rules_max_per_minute, DEFAULT_SETTINGS["run_rules_max_per_minute"])

    def test_non_list_kinds_coerced_to_empty_list(self):
        settings = normalize_zigbee2mqtt_settings({"run_rules_kinds": "not_a_list"})
        self.assertEqual(settings.run_rules_kinds, [])

    def test_none_input_returns_all_defaults(self):
        settings = normalize_zigbee2mqtt_settings(None)
        self.assertFalse(settings.run_rules_on_event)
        self.assertEqual(settings.run_rules_debounce_seconds, DEFAULT_SETTINGS["run_rules_debounce_seconds"])
        self.assertEqual(settings.run_rules_max_per_minute, DEFAULT_SETTINGS["run_rules_max_per_minute"])
        self.assertEqual(settings.run_rules_kinds, [])


class MaskZigbee2mqttSettingsRunRulesTests(SimpleTestCase):
    """Regression tests: mask output must include run_rules_* fields."""

    def test_mask_includes_run_rules_fields(self):
        masked = mask_zigbee2mqtt_settings({
            "enabled": True,
            "base_topic": "zigbee2mqtt",
            "run_rules_on_event": True,
            "run_rules_debounce_seconds": 3,
            "run_rules_max_per_minute": 30,
            "run_rules_kinds": ["trigger"],
        })
        self.assertTrue(masked["run_rules_on_event"])
        self.assertEqual(masked["run_rules_debounce_seconds"], 3)
        self.assertEqual(masked["run_rules_max_per_minute"], 30)
        self.assertEqual(masked["run_rules_kinds"], ["trigger"])

    def test_mask_defaults_when_fields_missing(self):
        masked = mask_zigbee2mqtt_settings({})
        self.assertIn("run_rules_on_event", masked)
        self.assertIn("run_rules_debounce_seconds", masked)
        self.assertIn("run_rules_max_per_minute", masked)
        self.assertIn("run_rules_kinds", masked)
