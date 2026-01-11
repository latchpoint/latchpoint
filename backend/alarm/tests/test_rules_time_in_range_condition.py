from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import TestCase

from alarm.rules.conditions import eval_condition_explain_with_context, eval_condition_with_context, validate_when_node


class RulesTimeInRangeConditionTests(TestCase):
    def test_matches_wrap_across_midnight(self):
        node = {
            "op": "time_in_range",
            "start": "22:00",
            "end": "06:00",
            "tz": "UTC",
        }

        self.assertTrue(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 1, 23, 0, tzinfo=ZoneInfo("UTC")))
        )
        self.assertTrue(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 2, 5, 59, tzinfo=ZoneInfo("UTC")))
        )
        self.assertFalse(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 2, 6, 0, tzinfo=ZoneInfo("UTC")))
        )
        self.assertFalse(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 2, 7, 0, tzinfo=ZoneInfo("UTC")))
        )

    def test_matches_non_wrapping_range(self):
        node = {
            "op": "time_in_range",
            "start": "09:00",
            "end": "17:00",
            "tz": "UTC",
        }

        self.assertTrue(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC")))
        )
        self.assertTrue(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 1, 16, 59, tzinfo=ZoneInfo("UTC")))
        )
        self.assertFalse(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 1, 17, 0, tzinfo=ZoneInfo("UTC")))
        )

    def test_respects_days_filter(self):
        node = {
            "op": "time_in_range",
            "start": "00:00",
            "end": "23:59",
            "days": ["mon"],
            "tz": "UTC",
        }

        # 2026-01-05 is Monday, 2026-01-06 is Tuesday
        self.assertTrue(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 5, 12, 0, tzinfo=ZoneInfo("UTC")))
        )
        self.assertFalse(
            eval_condition_with_context(node, entity_state={}, now=datetime(2026, 1, 6, 12, 0, tzinfo=ZoneInfo("UTC")))
        )

    def test_explain_includes_op(self):
        node = {
            "op": "time_in_range",
            "start": "09:00",
            "end": "17:00",
            "tz": "UTC",
        }
        ok, trace = eval_condition_explain_with_context(
            node, entity_state={}, now=datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        )
        self.assertTrue(ok)
        self.assertEqual(trace["op"], "time_in_range")


class RulesTimeInRangeValidationTests(TestCase):
    def test_rejects_invalid_time_format(self):
        errors = validate_when_node(
            {
                "op": "time_in_range",
                "start": "9:00",
                "end": "06:00",
                "tz": "UTC",
            }
        )
        self.assertIsNotNone(errors)
        self.assertIn("start", errors)

    def test_rejects_start_equal_end(self):
        errors = validate_when_node(
            {
                "op": "time_in_range",
                "start": "06:00",
                "end": "06:00",
                "tz": "UTC",
            }
        )
        self.assertIsNotNone(errors)
        self.assertIn("end", errors)

    def test_guardrail_rejects_time_only_rules(self):
        errors = validate_when_node(
            {
                "op": "time_in_range",
                "start": "22:00",
                "end": "06:00",
                "tz": "UTC",
            }
        )
        self.assertIsNotNone(errors)
        self.assertIn("non_field_errors", errors)

    def test_guardrail_allows_time_as_guard(self):
        errors = validate_when_node(
            {
                "op": "all",
                "children": [
                    {
                        "op": "time_in_range",
                        "start": "22:00",
                        "end": "06:00",
                        "tz": "UTC",
                    },
                    {
                        "op": "entity_state",
                        "entity_id": "binary_sensor.front_door",
                        "equals": "on",
                    },
                ],
            }
        )
        self.assertIsNone(errors)

