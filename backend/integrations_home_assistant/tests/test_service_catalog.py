from __future__ import annotations

import json

from django.test import SimpleTestCase

from integrations_home_assistant import impl


class _FakeResponse:
    """Minimal stand-in for the urlopen() context-manager response."""

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Type": "application/json"}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_HA_SERVICES_PAYLOAD = [
    {
        "domain": "light",
        "services": {
            "turn_on": {
                "name": "Turn on",
                "description": "Turns on one or more lights.",
                "target": {"entity": [{"domain": ["light"]}]},
                "fields": {
                    "transition": {
                        "selector": {"number": {"min": 0, "max": 300}},
                        "filter": {"supported_features": [32]},
                    },
                    "rgb_color": {
                        "name": "Color",
                        "selector": {"color_rgb": None},
                        "example": "[255, 100, 100]",
                    },
                    "advanced_fields": {
                        "collapsed": True,
                        "fields": {
                            "brightness": {"selector": {"number": {"min": 0, "max": 255}}},
                        },
                    },
                },
            },
            "turn_off": {"name": "Turn off", "description": "Turns off one or more lights."},
        },
    },
    {"domain": "broken", "services": ["not-a-dict"]},
    {"domain": "", "services": {"noop": {}}},
]


class ListServiceCatalogTests(SimpleTestCase):
    def _catalog(self, payload=None):
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            return _FakeResponse(_HA_SERVICES_PAYLOAD if payload is None else payload)

        catalog = impl.list_service_catalog(
            base_url="http://ha.local",
            token="tok",
            urlopen=fake_urlopen,
        )
        return catalog, captured

    def test_fetches_ha_services_endpoint(self):
        _, captured = self._catalog()
        self.assertEqual(captured["url"], "http://ha.local/api/services")

    def test_flattens_domains_into_sorted_domain_service_entries(self):
        catalog, _ = self._catalog()
        self.assertEqual(
            [(item["domain"], item["service"]) for item in catalog],
            [("light", "turn_off"), ("light", "turn_on")],
        )
        turn_off = catalog[0]
        self.assertEqual(turn_off["name"], "Turn off")
        self.assertEqual(turn_off["fields"], {})
        self.assertNotIn("target", turn_off)

    def test_slims_fields_to_ui_relevant_keys(self):
        catalog, _ = self._catalog()
        turn_on = catalog[1]
        self.assertEqual(turn_on["target"], {"entity": [{"domain": ["light"]}]})
        self.assertEqual(
            turn_on["fields"]["rgb_color"],
            {"name": "Color", "selector": {"color_rgb": None}, "example": "[255, 100, 100]"},
        )
        # Non-UI keys like "filter" are dropped.
        self.assertEqual(turn_on["fields"]["transition"], {"selector": {"number": {"min": 0, "max": 300}}})

    def test_hoists_collapsed_sections_into_flat_field_map(self):
        catalog, _ = self._catalog()
        fields = catalog[1]["fields"]
        self.assertNotIn("advanced_fields", fields)
        self.assertEqual(fields["brightness"], {"selector": {"number": {"min": 0, "max": 255}}})

    def test_skips_malformed_rows(self):
        catalog, _ = self._catalog()
        self.assertTrue(all(item["domain"] == "light" for item in catalog))

    def test_returns_empty_when_not_configured(self):
        catalog = impl.list_service_catalog(base_url="", token="", urlopen=None)
        self.assertEqual(catalog, [])
