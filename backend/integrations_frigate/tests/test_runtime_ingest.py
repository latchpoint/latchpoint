from __future__ import annotations

import json

from django.test import TestCase
from django.utils import timezone

from integrations_frigate.config import FrigateSettings
from integrations_frigate.models import FrigateDetection
from integrations_frigate.runtime import _handle_frigate_message


class FrigateRuntimeIngestTests(TestCase):
    def test_upserts_by_event_id(self):
        settings = FrigateSettings(
            enabled=True,
            events_topic="frigate/events",
            retention_seconds=3600,
            run_rules_on_event=False,
            run_rules_debounce_seconds=2,
            run_rules_max_per_minute=30,
            run_rules_kinds=["trigger"],
            known_cameras=[],
            known_zones_by_camera={},
        )
        now = timezone.now()
        payload = {
            "type": "new",
            "after": {
                "id": "evt1",
                "camera": "backyard",
                "label": "person",
                "top_score": 0.5,
                "entered_zones": ["yard"],
                "end_time": now.timestamp(),
            },
        }
        _handle_frigate_message(settings=settings, topic="frigate/events", payload=json.dumps(payload))
        self.assertEqual(FrigateDetection.objects.count(), 1)
        det = FrigateDetection.objects.get()
        self.assertAlmostEqual(det.confidence_pct, 50.0, places=5)

        payload["after"]["top_score"] = 0.9
        _handle_frigate_message(settings=settings, topic="frigate/events", payload=json.dumps(payload))
        self.assertEqual(FrigateDetection.objects.count(), 1)
        det = FrigateDetection.objects.get()
        self.assertAlmostEqual(det.confidence_pct, 90.0, places=5)

    def test_ignores_non_person_labels(self):
        settings = FrigateSettings(
            enabled=True,
            events_topic="frigate/events",
            retention_seconds=3600,
            run_rules_on_event=False,
            run_rules_debounce_seconds=2,
            run_rules_max_per_minute=30,
            run_rules_kinds=["trigger"],
            known_cameras=[],
            known_zones_by_camera={},
        )
        payload = {
            "type": "new",
            "after": {"id": "evt1", "camera": "backyard", "label": "car", "top_score": 0.9},
        }
        _handle_frigate_message(settings=settings, topic="frigate/events", payload=json.dumps(payload))
        self.assertEqual(FrigateDetection.objects.count(), 0)
