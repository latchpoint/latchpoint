from __future__ import annotations

import time
from datetime import datetime

from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase


class SystemTimeApiTests(APITestCase):
    def test_system_time_unauthenticated_ok(self):
        url = reverse("system-time")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIn("timestamp", payload)
        self.assertIn("timezone", payload)
        self.assertIn("epochMs", payload)
        self.assertIn("formatted", payload)

    @override_settings(TIME_ZONE="America/Los_Angeles")
    def test_system_time_timezone_matches_settings(self):
        url = reverse("system-time")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["timezone"], "America/Los_Angeles")

    def test_system_time_epoch_ms_close_to_now(self):
        url = reverse("system-time")
        before_ms = int(time.time() * 1000)
        response = self.client.get(url)
        after_ms = int(time.time() * 1000)
        self.assertEqual(response.status_code, 200)
        epoch_ms = response.json()["data"]["epochMs"]
        self.assertGreaterEqual(epoch_ms, before_ms - 1000)
        self.assertLessEqual(epoch_ms, after_ms + 1000)

    def test_system_time_iso_parses_as_aware(self):
        url = reverse("system-time")
        response = self.client.get(url)
        timestamp = response.json()["data"]["timestamp"]
        parsed = datetime.fromisoformat(timestamp)
        self.assertIsNotNone(parsed.tzinfo)
