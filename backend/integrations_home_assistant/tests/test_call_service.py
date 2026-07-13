from __future__ import annotations

import json

from django.test import SimpleTestCase

from integrations_home_assistant import impl


class _FakeResponse:
    """Minimal stand-in for the urlopen() context-manager response.

    ``read`` is only exposed when a ``body`` is supplied, so tests that don't care about the
    response body exercise the "body unavailable" branch of ``_read_changed_states``.
    """

    def __init__(self, status: int = 200, body: bytes | None = None):
        self.status = status
        if body is not None:
            self.read = lambda: body

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

    def _call(self, *, target=None, service_data=None, response_body: bytes | None = None):
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse(200, body=response_body)

        impl.call_service(
            base_url="http://ha.local",
            token="tok",
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


class CallServiceNoOpVisibilityTests(SimpleTestCase):
    """A 2xx response that changed no states is the fingerprint of a silent no-op.

    HA returns the list of states it changed. An optimistic / script-backed light (e.g. the Inovelli
    LED-bar template light) accepts ``light.turn_on`` with a 2xx but changes nothing when its backing
    scripts are contended — which previously surfaced as ``ok:true`` with no signal. ``call_service``
    must log a warning so the failure is diagnosable from the backend alone.
    """

    def _call(self, *, response_body: bytes | None):
        def fake_urlopen(request, timeout=None):
            return _FakeResponse(200, body=response_body)

        impl.call_service(
            base_url="http://ha.local",
            token="tok",
            urlopen=fake_urlopen,
            domain="light",
            service="turn_on",
            target={"entity_ids": ["light.inovelli_led_bars"]},
            service_data={"rgb_color": [255, 0, 0], "brightness_pct": 100},
        )

    def test_zero_changed_states_logs_possible_no_op(self):
        with self.assertLogs("integrations_home_assistant.impl", level="WARNING") as cm:
            self._call(response_body=b"[]")
        self.assertTrue(
            any("changed 0 states" in line for line in cm.output),
            cm.output,
        )

    def test_changed_states_response_does_not_warn(self):
        with self.assertNoLogs("integrations_home_assistant.impl", level="WARNING"):
            self._call(response_body=b'[{"entity_id": "light.inovelli_led_bars", "state": "on"}]')

    def test_missing_body_does_not_warn(self):
        # When the response body is unavailable we can't tell no-op from success — stay quiet.
        with self.assertNoLogs("integrations_home_assistant.impl", level="WARNING"):
            self._call(response_body=None)
