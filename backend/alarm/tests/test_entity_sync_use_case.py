from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from alarm.models import Entity
from alarm.use_cases.entity_sync import sync_entities_from_home_assistant


class EntitySyncUseCaseTests(TestCase):
    def test_sync_entities_creates_new_entities(self):
        items = [
            {
                "entity_id": "binary_sensor.front_door",
                "domain": "binary_sensor",
                "name": "Front Door",
                "state": "off",
                "device_class": "door",
            },
        ]
        result = sync_entities_from_home_assistant(items=items)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertTrue(Entity.objects.filter(entity_id="binary_sensor.front_door").exists())

    def test_sync_entities_updates_existing(self):
        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front Door",
            last_state="on",
        )
        items = [
            {
                "entity_id": "binary_sensor.front_door",
                "domain": "binary_sensor",
                "name": "Front Door Updated",
                "state": "off",
            },
        ]
        result = sync_entities_from_home_assistant(items=items)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["updated"], 1)

        entity = Entity.objects.get(entity_id="binary_sensor.front_door")
        self.assertEqual(entity.name, "Front Door Updated")
        self.assertEqual(entity.last_state, "off")

    def test_sync_entities_ignores_invalid_payloads(self):
        items = [
            None,
            "not a dict",
            {"entity_id": "invalid"},  # No dot in entity_id
            {"entity_id": ""},
            {},
        ]
        result = sync_entities_from_home_assistant(items=items)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["updated"], 0)

    def test_sync_entities_extracts_domain_from_entity_id(self):
        items = [
            {
                "entity_id": "light.living_room",
                "name": "Living Room Light",
                "state": "on",
            },
        ]
        result = sync_entities_from_home_assistant(items=items)
        self.assertEqual(result["imported"], 1)

        entity = Entity.objects.get(entity_id="light.living_room")
        self.assertEqual(entity.domain, "light")

    def test_sync_entities_uses_entity_id_as_name_when_missing(self):
        items = [
            {
                "entity_id": "switch.garage",
                "state": "off",
            },
        ]
        result = sync_entities_from_home_assistant(items=items)
        self.assertEqual(result["imported"], 1)

        entity = Entity.objects.get(entity_id="switch.garage")
        self.assertEqual(entity.name, "switch.garage")

    def test_sync_entities_sets_source_to_home_assistant(self):
        items = [
            {
                "entity_id": "sensor.temperature",
                "name": "Temperature",
                "state": "72",
            },
        ]
        sync_entities_from_home_assistant(items=items)
        entity = Entity.objects.get(entity_id="sensor.temperature")
        self.assertEqual(entity.source, "home_assistant")

    def test_sync_entities_includes_timestamp(self):
        now = timezone.now()
        items = [
            {
                "entity_id": "binary_sensor.motion",
                "name": "Motion",
                "state": "off",
            },
        ]
        result = sync_entities_from_home_assistant(items=items, now=now)
        self.assertEqual(result["timestamp"], now)
