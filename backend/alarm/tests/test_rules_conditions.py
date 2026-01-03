from __future__ import annotations

from django.test import SimpleTestCase

from alarm.rules.conditions import eval_condition, eval_condition_explain, extract_for


class RuleConditionsTests(SimpleTestCase):
    def test_extract_for_returns_child_and_seconds(self):
        seconds, child = extract_for({"op": "for", "seconds": 5, "child": {"op": "entity_state"}})
        self.assertEqual(seconds, 5)
        self.assertEqual(child, {"op": "entity_state"})

    def test_extract_for_invalid_seconds_returns_none(self):
        seconds, child = extract_for({"op": "for", "seconds": 0, "child": {"op": "entity_state"}})
        self.assertIsNone(seconds)
        self.assertEqual(child, {"op": "entity_state"})

    def test_eval_condition_entity_state(self):
        node = {"op": "entity_state", "entity_id": "binary_sensor.front", "equals": "on"}
        self.assertTrue(eval_condition(node, entity_state={"binary_sensor.front": "on"}))
        self.assertFalse(eval_condition(node, entity_state={"binary_sensor.front": "off"}))

    def test_eval_condition_any_all_not(self):
        on = {"op": "entity_state", "entity_id": "x", "equals": "on"}
        off = {"op": "entity_state", "entity_id": "y", "equals": "off"}
        self.assertTrue(eval_condition({"op": "all", "children": [on, off]}, entity_state={"x": "on", "y": "off"}))
        self.assertTrue(eval_condition({"op": "any", "children": [on, off]}, entity_state={"x": "no", "y": "off"}))
        self.assertTrue(eval_condition({"op": "not", "child": on}, entity_state={"x": "off"}))

    def test_eval_condition_invalid_nodes_are_false(self):
        self.assertFalse(eval_condition(None, entity_state={}))
        self.assertFalse(eval_condition({}, entity_state={}))
        self.assertFalse(eval_condition({"op": "all", "children": []}, entity_state={}))
        self.assertFalse(eval_condition({"op": "entity_state", "entity_id": 1, "equals": "on"}, entity_state={}))

    def test_eval_condition_explain_unknown_op(self):
        ok, trace = eval_condition_explain({"op": "nope"}, entity_state={})
        self.assertFalse(ok)
        self.assertEqual(trace["reason"], "unsupported_op")

    def test_eval_condition_explain_entity_state_includes_actual_expected(self):
        ok, trace = eval_condition_explain(
            {"op": "entity_state", "entity_id": "x", "equals": "on"},
            entity_state={"x": "off"},
        )
        self.assertFalse(ok)
        self.assertEqual(trace["expected"], "on")
        self.assertEqual(trace["actual"], "off")

