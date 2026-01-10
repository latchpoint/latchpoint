from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import Entity, Rule, RuleEntityRef


class TestRuleEntitySourceHints(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rules-source@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_rule_backfills_entity_source_from_definition(self):
        url = reverse("alarm-rules")
        payload = {
            "name": "R1",
            "enabled": True,
            "priority": 1,
            "schema_version": 1,
            "definition": {
                "when": {
                    "op": "entity_state",
                    "entity_id": "binary_sensor.front_door",
                    "equals": "on",
                    "source": "home_assistant",
                },
                "then": [{"type": "alarm_trigger"}],
            },
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 201)

        rule = Rule.objects.get(name="R1")
        self.assertTrue(RuleEntityRef.objects.filter(rule=rule, entity__entity_id="binary_sensor.front_door").exists())

        entity = Entity.objects.get(entity_id="binary_sensor.front_door")
        self.assertEqual(entity.source, "home_assistant")

    def test_create_rule_does_not_overwrite_existing_entity_source(self):
        Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front Door",
            source="zwavejs",
        )

        url = reverse("alarm-rules")
        payload = {
            "name": "R2",
            "enabled": True,
            "priority": 1,
            "schema_version": 1,
            "definition": {
                "when": {
                    "op": "entity_state",
                    "entity_id": "binary_sensor.front_door",
                    "equals": "on",
                    "source": "home_assistant",
                },
                "then": [{"type": "alarm_trigger"}],
            },
        }

        response = self.client.post(url, data=payload, format="json")
        self.assertEqual(response.status_code, 201)

        entity = Entity.objects.get(entity_id="binary_sensor.front_door")
        self.assertEqual(entity.source, "zwavejs")

