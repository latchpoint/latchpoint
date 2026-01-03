from __future__ import annotations

from django.test import SimpleTestCase

from alarm.domain.entity_state import normalize_contact_state


class EntityStateNormalizationTests(SimpleTestCase):
    def test_normalize_contact_state_unknown_cases(self):
        for raw in [None, "", "unknown", "UNAVAILABLE", " none ", "Null"]:
            self.assertEqual(normalize_contact_state(raw), "unknown")

    def test_normalize_contact_state_open_cases(self):
        for raw in ["on", "open", "opened", "TRUE", "1", "  On  "]:
            self.assertEqual(normalize_contact_state(raw), "open")

    def test_normalize_contact_state_closed_cases(self):
        for raw in ["off", "closed", "FALSE", "0", "  off  "]:
            self.assertEqual(normalize_contact_state(raw), "closed")

    def test_normalize_contact_state_fallback(self):
        self.assertEqual(normalize_contact_state("weird"), "unknown")

