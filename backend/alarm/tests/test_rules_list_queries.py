from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import Entity, Rule, RuleEntityRef, RuleKind


class TestRulesListQueries(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rules@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_rules_list_is_constant_queries(self):
        first = Rule.objects.create(name="One", kind=RuleKind.TRIGGER, enabled=True, priority=1)
        second = Rule.objects.create(name="Two", kind=RuleKind.TRIGGER, enabled=True, priority=0)
        entity = Entity.objects.create(
            entity_id="binary_sensor.front_door",
            domain="binary_sensor",
            name="Front Door",
        )
        RuleEntityRef.objects.create(rule=first, entity=entity)
        RuleEntityRef.objects.create(rule=second, entity=entity)

        url = reverse("alarm-rules")
        with self.assertNumQueries(3):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

