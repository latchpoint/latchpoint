from __future__ import annotations

from django.test import SimpleTestCase
from django.utils import timezone

from integrations_frigate.parsing import normalize_confidence_pct, parse_frigate_events_payload


class FrigateParsingTests(SimpleTestCase):
    def test_normalize_confidence_pct_accepts_fraction(self):
        self.assertEqual(normalize_confidence_pct(0.9), 90.0)

    def test_normalize_confidence_pct_accepts_percent(self):
        self.assertEqual(normalize_confidence_pct(90), 90.0)

    def test_parse_frigate_events_payload_parses_common_shape(self):
        now = timezone.now()
        payload = {
            "type": "new",
            "after": {
                "id": "abc123",
                "camera": "backyard",
                "label": "person",
                "top_score": 0.91,
                "entered_zones": ["yard"],
                "end_time": now.timestamp(),
            },
        }
        parsed = parse_frigate_events_payload(payload)
        assert parsed is not None
        self.assertEqual(parsed.event_id, "abc123")
        self.assertEqual(parsed.camera, "backyard")
        self.assertEqual(parsed.label, "person")
        self.assertEqual(parsed.zones, ["yard"])
        self.assertAlmostEqual(parsed.confidence_pct, 91.0, places=5)

    def test_parse_frigate_events_payload_accepts_direct_event_shape(self):
        now = timezone.now()
        payload = {
            "id": "evt2",
            "camera": "front",
            "label": "person",
            "top_score": 90,  # already percent
            "current_zones": ["porch"],
            "start_time": now.timestamp(),
        }
        parsed = parse_frigate_events_payload(payload)
        assert parsed is not None
        self.assertEqual(parsed.event_id, "evt2")
        self.assertEqual(parsed.camera, "front")
        self.assertEqual(parsed.zones, ["porch"])
        self.assertAlmostEqual(parsed.confidence_pct, 90.0, places=5)

    def test_parse_frigate_events_payload_requires_after(self):
        self.assertIsNone(parse_frigate_events_payload({"type": "new"}))
