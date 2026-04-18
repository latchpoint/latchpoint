"""Tests for ADR 0084: stop_group API surface (distinct-groups endpoint + validator)."""

from __future__ import annotations

from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from alarm.models import Rule, RuleKind


class StopGroupsEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sg@example.com", password="pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make_rule(self, *, name: str, stop_group: str = "") -> Rule:
        return Rule.objects.create(
            name=name,
            kind=RuleKind.TRIGGER,
            enabled=True,
            priority=1,
            stop_group=stop_group,
            schema_version=1,
            definition={"when": None, "then": []},
        )

    def _body(self, resp):
        """Unwrap the global response envelope; tolerate responses already unwrapped."""
        data = resp.json()
        return data.get("data", data) if isinstance(data, dict) else data

    def test_returns_empty_list_when_no_groups_in_use(self):
        self._make_rule(name="ungrouped-1", stop_group="")
        self._make_rule(name="ungrouped-2", stop_group="")

        url = reverse("alarm-rules-stop-groups")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._body(resp), {"groups": []})

    def test_returns_distinct_non_empty_groups_sorted(self):
        self._make_rule(name="a1", stop_group="door-entry")
        self._make_rule(name="a2", stop_group="door-entry")  # duplicate
        self._make_rule(name="b", stop_group="perimeter")
        self._make_rule(name="c", stop_group="")  # excluded

        url = reverse("alarm-rules-stop-groups")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._body(resp), {"groups": ["door-entry", "perimeter"]})


class StopProcessingValidatorTests(APITestCase):
    """stop_processing=True must require a non-empty stop_group (ADR 0084)."""

    def setUp(self):
        self.user = User.objects.create_user(email="sgval@example.com", password="pass", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _body(self, resp):
        data = resp.json()
        return data.get("data", data) if isinstance(data, dict) else data

    def _errors(self, resp) -> dict:
        """Extract validation-error details from the envelope format."""
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and "details" in err:
                return err["details"] or {}
            return data
        return {}

    def _payload(self, *, stop_processing: bool, stop_group: str) -> dict:
        return {
            "name": "Rule",
            "enabled": True,
            "priority": 10,
            "stop_processing": stop_processing,
            "stop_group": stop_group,
            "schema_version": 1,
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.x", "equals": "on"},
                "then": [{"type": "alarm_trigger"}],
            },
        }

    def test_post_rejects_stop_processing_without_group(self):
        url = reverse("alarm-rules")
        resp = self.client.post(url, data=self._payload(stop_processing=True, stop_group=""), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("stop_group", self._errors(resp))

    def test_post_accepts_stop_processing_with_group(self):
        url = reverse("alarm-rules")
        resp = self.client.post(
            url,
            data=self._payload(stop_processing=True, stop_group="door-entry"),
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        body = self._body(resp)
        self.assertTrue(body["stop_processing"])
        self.assertEqual(body["stop_group"], "door-entry")

    def test_post_accepts_stop_group_without_stop_processing(self):
        """A rule can have a stop_group set without being a stopper — it simply participates passively."""
        url = reverse("alarm-rules")
        resp = self.client.post(
            url,
            data=self._payload(stop_processing=False, stop_group="door-entry"),
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        body = self._body(resp)
        self.assertFalse(body["stop_processing"])
        self.assertEqual(body["stop_group"], "door-entry")

    def test_post_strips_whitespace_stop_group(self):
        """Surrounding whitespace on stop_group must be stripped before persisting."""
        url = reverse("alarm-rules")
        resp = self.client.post(
            url,
            data=self._payload(stop_processing=True, stop_group="  door-entry  "),
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        body = self._body(resp)
        self.assertEqual(body["stop_group"], "door-entry")

    def test_post_rejects_whitespace_only_stop_group_when_stopping(self):
        """A whitespace-only stop_group is equivalent to empty once stripped and must be rejected."""
        url = reverse("alarm-rules")
        resp = self.client.post(
            url,
            data=self._payload(stop_processing=True, stop_group="   "),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("stop_group", self._errors(resp))

    def test_patch_rejects_enabling_stop_processing_without_group(self):
        """PATCH that flips stop_processing=True while stop_group is still empty must fail."""
        create = self.client.post(
            reverse("alarm-rules"),
            data=self._payload(stop_processing=False, stop_group=""),
            format="json",
        )
        self.assertEqual(create.status_code, 201)
        rule_id = self._body(create)["id"]

        resp = self.client.patch(
            reverse("alarm-rule-detail", args=[rule_id]),
            data={"stop_processing": True},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("stop_group", self._errors(resp))
