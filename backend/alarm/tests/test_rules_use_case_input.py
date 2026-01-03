from __future__ import annotations

from django.test import SimpleTestCase

from alarm.use_cases import rules as rules_uc


class RulesUseCaseInputTests(SimpleTestCase):
    def test_parse_simulate_input_cleans_entity_states(self):
        data = {
            "entity_states": {" binary_sensor.front ": "on", "": "x", 1: "y", "ok": 2},
            "assume_for_seconds": 5,
        }
        parsed = rules_uc.parse_simulate_input(data)
        self.assertEqual(parsed.entity_states, {"binary_sensor.front": "on"})
        self.assertEqual(parsed.assume_for_seconds, 5)

    def test_parse_simulate_input_rejects_non_object_entity_states(self):
        with self.assertRaises(rules_uc.RuleSimulateInputError):
            rules_uc.parse_simulate_input({"entity_states": []})

    def test_parse_simulate_input_rejects_non_int_assume_for_seconds(self):
        with self.assertRaises(rules_uc.RuleSimulateInputError):
            rules_uc.parse_simulate_input({"assume_for_seconds": "5"})

