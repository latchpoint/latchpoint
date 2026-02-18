from __future__ import annotations

from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.dispatcher.config import DispatcherConfig
from alarm.models import Rule, RuleRuntimeState


class DispatcherApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="dispatcher@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_dispatcher_endpoints_require_auth(self):
        client = APIClient()

        self.assertEqual(client.get(reverse("dispatcher-status")).status_code, 401)
        self.assertEqual(client.get(reverse("dispatcher-config")).status_code, 401)
        self.assertEqual(client.get(reverse("dispatcher-suspended-rules")).status_code, 401)
        self.assertEqual(client.delete(reverse("dispatcher-suspended-rules")).status_code, 401)

    @patch("alarm.dispatcher.get_dispatcher_status")
    def test_status_returns_dispatcher_snapshot(self, mock_get_dispatcher_status):
        mock_get_dispatcher_status.return_value = {
            "enabled": True,
            "pending_entities": 0,
            "pending_batches": 0,
        }

        response = self.client.get(reverse("dispatcher-status"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["enabled"], True)
        self.assertIn("pending_entities", body["data"])

    @patch("alarm.dispatcher.config.get_dispatcher_config")
    def test_config_returns_dispatcher_config(self, mock_get_dispatcher_config):
        mock_get_dispatcher_config.return_value = DispatcherConfig(
            debounce_ms=150,
            batch_size_limit=25,
            rate_limit_per_sec=7,
            rate_limit_burst=15,
            worker_concurrency=3,
            queue_max_depth=400,
        )

        response = self.client.get(reverse("dispatcher-config"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["enabled"], True)
        self.assertEqual(body["data"]["debounce_ms"], 150)
        self.assertEqual(body["data"]["queue_max_depth"], 400)

    def test_suspended_rules_returns_suspended_entries(self):
        rule = Rule.objects.create(name="Suspended Rule", kind="trigger", definition={})
        runtime = RuleRuntimeState.objects.create(
            rule=rule,
            node_id="root",
            error_suspended=True,
            consecutive_failures=3,
            last_error="boom",
            last_failure_at=timezone.now(),
            next_allowed_at=timezone.now(),
        )

        response = self.client.get(reverse("dispatcher-suspended-rules"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(len(body["data"]), 1)
        row = body["data"][0]
        self.assertEqual(row["rule_id"], rule.id)
        self.assertEqual(row["rule_name"], "Suspended Rule")
        self.assertEqual(row["node_id"], runtime.node_id)
        self.assertEqual(row["consecutive_failures"], 3)

    def test_delete_suspended_rule_clears_state(self):
        rule = Rule.objects.create(name="Rule To Clear", kind="trigger", definition={})
        runtime = RuleRuntimeState.objects.create(
            rule=rule,
            node_id="root",
            error_suspended=True,
            consecutive_failures=2,
            last_error="bad",
            last_failure_at=timezone.now(),
            next_allowed_at=timezone.now(),
        )

        response = self.client.delete(f"{reverse('dispatcher-suspended-rules')}?rule_id={rule.id}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("data", body)
        self.assertEqual(body["data"]["cleared"], 1)

        runtime.refresh_from_db()
        self.assertEqual(runtime.error_suspended, False)
        self.assertEqual(runtime.consecutive_failures, 0)

    def test_delete_suspended_rule_returns_standard_not_found_error(self):
        response = self.client.delete(f"{reverse('dispatcher-suspended-rules')}?rule_id=999999")
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertIn("error", body)
        self.assertEqual(body["error"]["status"], "not_found")
        self.assertIn("not suspended", body["error"]["message"].lower())
