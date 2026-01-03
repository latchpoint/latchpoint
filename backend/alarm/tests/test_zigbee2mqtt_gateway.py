from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase

from alarm.gateways.zigbee2mqtt import DefaultZigbee2mqttGateway
from alarm.models import AlarmSettingsProfile, Entity
from alarm.tests.settings_test_utils import set_profile_settings


class Zigbee2mqttGatewayTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(
            self.profile,
            mqtt_connection={"enabled": True, "host": "mqtt.local", "port": 1883},
            zigbee2mqtt={"enabled": True, "base_topic": "zigbee2mqtt"},
        )
        self.gateway = DefaultZigbee2mqttGateway()

        self.definition = {
            "exposes": [
                {"type": "binary", "name": "state", "property": "state", "access": 3},
                {"type": "numeric", "name": "brightness", "property": "brightness", "access": 3, "value_min": 0, "value_max": 255},
            ]
        }

        self.entity = Entity.objects.create(
            entity_id="z2m_switch.0x00124b0018e2abcd_state",
            domain="switch",
            name="front_light state",
            source="zigbee2mqtt",
            attributes={
                "zigbee2mqtt": {
                    "ieee_address": "0x00124b0018e2abcd",
                    "friendly_name": "front_light",
                    "definition": self.definition,
                    "expose": {"type": "binary", "name": "state", "property": "state", "access": 3},
                }
            },
        )

    @patch("alarm.gateways.zigbee2mqtt.mqtt_connection_manager.publish")
    def test_set_entity_value_state_bool_publishes_on_off(self, mock_publish):
        self.gateway.set_entity_value(entity_id=self.entity.entity_id, value=True)
        self.assertTrue(mock_publish.called)
        _, kwargs = mock_publish.call_args
        self.assertEqual(kwargs["topic"], "zigbee2mqtt/front_light/set")
        self.assertEqual(json.loads(kwargs["payload"]), {"state": "ON"})

    @patch("alarm.gateways.zigbee2mqtt.mqtt_connection_manager.publish")
    def test_set_entity_value_payload_dict_validates_and_publishes(self, mock_publish):
        self.gateway.set_entity_value(entity_id=self.entity.entity_id, value={"state": "OFF", "brightness": 200})
        _, kwargs = mock_publish.call_args
        self.assertEqual(kwargs["topic"], "zigbee2mqtt/front_light/set")
        self.assertEqual(json.loads(kwargs["payload"]), {"state": "OFF", "brightness": 200})

    @patch("alarm.gateways.zigbee2mqtt.mqtt_connection_manager.publish")
    def test_set_entity_value_payload_dict_validates_nested_exposes(self, mock_publish):
        self.entity.attributes["zigbee2mqtt"]["definition"] = {
            "exposes": [
                {
                    "type": "light",
                    "features": [
                        {"type": "binary", "name": "state", "property": "state", "access": 3},
                        {"type": "numeric", "name": "brightness", "property": "brightness", "access": 3, "value_min": 0, "value_max": 255},
                    ],
                }
            ]
        }
        self.entity.save(update_fields=["attributes"])

        self.gateway.set_entity_value(entity_id=self.entity.entity_id, value={"state": True, "brightness": 1})
        _, kwargs = mock_publish.call_args
        self.assertEqual(json.loads(kwargs["payload"]), {"state": "ON", "brightness": 1})

    @patch("alarm.gateways.zigbee2mqtt.mqtt_connection_manager.publish")
    def test_set_entity_value_payload_dict_rejects_unknown_property(self, mock_publish):
        with self.assertRaises(ValueError) as ctx:
            self.gateway.set_entity_value(entity_id=self.entity.entity_id, value={"nope": True})
        self.assertIn("Unknown Zigbee2MQTT property", str(ctx.exception))
        self.assertFalse(mock_publish.called)

    @patch("alarm.gateways.zigbee2mqtt.mqtt_connection_manager.publish")
    def test_set_entity_value_payload_dict_rejects_non_writable(self, mock_publish):
        self.entity.attributes["zigbee2mqtt"]["definition"] = {
            "exposes": [{"type": "numeric", "name": "brightness", "property": "brightness", "access": 1}]
        }
        self.entity.save(update_fields=["attributes"])

        with self.assertRaises(ValueError) as ctx:
            self.gateway.set_entity_value(entity_id=self.entity.entity_id, value={"brightness": 100})
        self.assertIn("not writable", str(ctx.exception))
        self.assertFalse(mock_publish.called)
