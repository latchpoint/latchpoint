from __future__ import annotations

import json

from django.test import SimpleTestCase

from integrations_home_assistant import impl


class _FakeResponse:
    """Minimal stand-in for the urlopen() context-manager response."""

    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CallServiceTargetNormalizationTests(SimpleTestCase):
    """Regression for the lock-doors bug: HA rejects ``entity_ids`` (plural) with HTTP 400.

    The rules builder UI models the target as ``entityIds`` and the frontend snake-cases it to
    ``entity_ids`` on the wire. HA's service API only accepts the singular ``entity_id`` (even for
    a list), so ``call_service`` must normalize the target key before POSTing.
    """

    def _call(self, *, target=None, service_data=None):
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse(200)

        impl.call_service(
            base_url="http://ha.local",
            token="tok",
            get_client=lambda: None,  # force the REST fallback path
            urlopen=fake_urlopen,
            domain="lock",
            service="lock",
            target=target,
            service_data=service_data,
        )
        return captured

    def test_plural_entity_ids_is_normalized_to_entity_id(self):
        captured = self._call(target={"entity_ids": ["lock.front_door_lock", "lock.backyard_lock"]})
        self.assertEqual(captured["url"], "http://ha.local/api/services/lock/lock")
        self.assertNotIn("entity_ids", captured["body"])
        self.assertEqual(
            captured["body"].get("entity_id"),
            ["lock.front_door_lock", "lock.backyard_lock"],
        )

    def test_camelcase_entity_ids_is_normalized(self):
        captured = self._call(target={"entityIds": ["lock.front_door_lock"]})
        self.assertNotIn("entityIds", captured["body"])
        self.assertEqual(captured["body"].get("entity_id"), ["lock.front_door_lock"])

    def test_singular_entity_id_passes_through_unchanged(self):
        captured = self._call(target={"entity_id": ["lock.front_door_lock"]})
        self.assertEqual(captured["body"].get("entity_id"), ["lock.front_door_lock"])

    def test_service_data_merges_with_normalized_target(self):
        captured = self._call(
            target={"entity_ids": ["lock.front_door_lock"]},
            service_data={"code": "1234"},
        )
        self.assertEqual(captured["body"].get("entity_id"), ["lock.front_door_lock"])
        self.assertEqual(captured["body"].get("code"), "1234")
