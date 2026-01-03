from __future__ import annotations

import json

from django.core.cache import cache
from django.test import TestCase

from alarm.models import AlarmSettingsEntry, Entity
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from integrations_zigbee2mqtt.runtime import _CACHE_KEY_FRIENDLY_TO_IEEE, _entity_ids_cache_key, _handle_z2m_message, get_settings


class Zigbee2mqttRuntimeIngestTests(TestCase):
    def test_ingest_updates_only_known_entity_ids(self):
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

        ieee = "0x00124b0018e2abcd"
        friendly = "front_door"
        entity_id = f"z2m_sensor.{ieee}_battery"
        Entity.objects.create(
            entity_id=entity_id,
            domain="sensor",
            name="Battery",
            source="zigbee2mqtt",
            attributes={"zigbee2mqtt": {"ieee_address": ieee, "friendly_name": friendly}},
        )

        cache.set(_CACHE_KEY_FRIENDLY_TO_IEEE, {friendly: ieee}, timeout=None)
        cache.set(_entity_ids_cache_key(ieee=ieee), [entity_id], timeout=None)

        settings = get_settings()
        with self.assertNumQueries(1):
            _handle_z2m_message(settings=settings, topic=f"zigbee2mqtt/{friendly}", payload=json.dumps({"battery": 90}))

        updated = Entity.objects.get(entity_id=entity_id)
        self.assertEqual(updated.last_state, "90")
        self.assertIsNotNone(updated.last_seen)

    def test_ingest_skips_unknown_keys_without_db_writes(self):
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

        ieee = "0x00124b0018e2abcd"
        friendly = "front_door"
        entity_id = f"z2m_sensor.{ieee}_battery"
        Entity.objects.create(
            entity_id=entity_id,
            domain="sensor",
            name="Battery",
            source="zigbee2mqtt",
            attributes={"zigbee2mqtt": {"ieee_address": ieee, "friendly_name": friendly}},
        )

        cache.set(_CACHE_KEY_FRIENDLY_TO_IEEE, {friendly: ieee}, timeout=None)
        cache.set(_entity_ids_cache_key(ieee=ieee), [entity_id], timeout=None)

        settings = get_settings()
        with self.assertNumQueries(0):
            _handle_z2m_message(settings=settings, topic=f"zigbee2mqtt/{friendly}", payload=json.dumps({"unknown": 1}))

