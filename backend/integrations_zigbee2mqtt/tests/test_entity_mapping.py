from __future__ import annotations

from django.test import SimpleTestCase

from integrations_zigbee2mqtt.entity_mapping import build_entities_for_z2m_device, extract_ieee_mapping


class Zigbee2mqttEntityMappingTests(SimpleTestCase):
    def test_build_entities_for_device_creates_sensor_and_action_entities(self):
        device = {
            "ieee_address": "0x00124b0018e2abcd",
            "friendly_name": "front_door",
            "definition": {
                "model": "MCCGQ11LM",
                "vendor": "Aqara",
                "exposes": [
                    {"type": "binary", "name": "contact", "property": "contact"},
                    {"type": "numeric", "name": "battery", "property": "battery"},
                    {"type": "enum", "name": "action", "property": "action"},
                ],
            },
        }

        entities = build_entities_for_z2m_device(device)
        ids = {e.entity_id for e in entities}
        self.assertIn("z2m_binary_sensor.0x00124b0018e2abcd_contact", ids)
        self.assertIn("z2m_sensor.0x00124b0018e2abcd_battery", ids)
        self.assertIn("z2m_action.0x00124b0018e2abcd", ids)

    def test_extract_ieee_mapping(self):
        devices = [
            {"friendly_name": "a", "ieee_address": "0x1"},
            {"friendly_name": "b", "ieee_address": "0x2"},
        ]
        self.assertEqual(extract_ieee_mapping(devices), {"a": "0x1", "b": "0x2"})

