from __future__ import annotations

import json
import threading
from unittest.mock import patch

from django.test import TestCase

from alarm.models import AlarmSettingsEntry, Entity
from alarm.use_cases.settings_profile import ensure_active_settings_profile


class _FakeMqttManager:
    def __init__(self):
        self._subs = {}
        self._on_connect = []

    def get_status(self):
        class _S:
            def as_dict(self):
                return {"configured": True, "enabled": True, "connected": True}

        return _S()

    def register_on_connect(self, cb):
        self._on_connect.append(cb)

    def subscribe(self, *, topic: str, qos: int = 0, callback=None):
        self._subs[topic] = callback

    def unsubscribe(self, *, topic: str, callback=None):
        current = self._subs.get(topic)
        if callback is None or current == callback:
            self._subs.pop(topic, None)

    def publish(self, *, topic: str, payload: str, qos: int = 0, retain: bool = False):
        # When a request is published, immediately deliver a response.
        if topic.endswith("/bridge/request/devices"):
            base = topic[: -len("/bridge/request/devices")]
            response_topic = f"{base}/bridge/response/devices"
            cb = self._subs.get(response_topic)
            if cb:
                devices = [
                    {
                        "ieee_address": "0x00124b0018e2abcd",
                        "friendly_name": "front_door",
                        "definition": {
                            "exposes": [
                                {"type": "binary", "name": "contact", "property": "contact"},
                            ]
                        },
                    }
                ]
                # Simulate a real MQTT client: callbacks run outside the caller thread.
                threading.Thread(
                    target=lambda: cb(topic=response_topic, payload=json.dumps(devices)),
                    daemon=True,
                ).start()


class Zigbee2mqttSyncDevicesTests(TestCase):
    def test_sync_devices_upserts_entities(self):
        profile = ensure_active_settings_profile()
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="mqtt_connection",
            defaults={"value_type": "json", "value": {"enabled": True, "host": "mqtt.local", "port": 1883}},
        )
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="zigbee2mqtt",
            defaults={"value_type": "json", "value": {"enabled": True, "base_topic": "zigbee2mqtt"}},
        )

        fake = _FakeMqttManager()
        with patch("integrations_zigbee2mqtt.runtime.mqtt_connection_manager", fake):
            from integrations_zigbee2mqtt.runtime import sync_devices_via_mqtt

            result = sync_devices_via_mqtt(timeout_seconds=0.2)

        self.assertTrue(result["ok"])
        self.assertEqual(result["devices"], 1)
        self.assertTrue(
            Entity.objects.filter(entity_id="z2m_binary_sensor.0x00124b0018e2abcd_contact", source="zigbee2mqtt").exists()
        )
