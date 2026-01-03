from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import Entity, Rule, RuleEntityRef, RuleKind


class TestRuleDetailQueries(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rule-detail@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_rule_detail_is_constant_queries(self):
        rule = Rule.objects.create(name="Detail", kind=RuleKind.TRIGGER, enabled=True, priority=1)
        entity = Entity.objects.create(entity_id="binary_sensor.front_door", domain="binary_sensor", name="Front Door")
        RuleEntityRef.objects.create(rule=rule, entity=entity)

        url = reverse("alarm-rule-detail", args=[rule.id])
        with self.assertNumQueries(3):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["entity_ids"], ["binary_sensor.front_door"])
