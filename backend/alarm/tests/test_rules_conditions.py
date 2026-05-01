from __future__ import annotations

from django.test import SimpleTestCase

from alarm.rules.conditions import (
    eval_condition,
    eval_condition_explain,
    extract_for,
    extract_when_entity_ids,
)


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


class ExtractWhenEntityIdsTests(SimpleTestCase):
    """Pin the contract used by ADR-0088 to bind ``{{trigger.*}}``."""

    def test_single_entity_state_emits_one_id(self):
        node = {"op": "entity_state", "entity_id": "binary_sensor.front", "equals": "on"}
        self.assertEqual(extract_when_entity_ids(node), ["binary_sensor.front"])

    def test_entity_state_with_blank_or_non_string_id_yields_nothing(self):
        self.assertEqual(extract_when_entity_ids({"op": "entity_state", "entity_id": "", "equals": "on"}), [])
        self.assertEqual(extract_when_entity_ids({"op": "entity_state", "entity_id": "   ", "equals": "on"}), [])
        self.assertEqual(extract_when_entity_ids({"op": "entity_state", "entity_id": 42, "equals": "on"}), [])

    def test_all_recurses_and_preserves_first_seen_order(self):
        node = {
            "op": "all",
            "children": [
                {"op": "entity_state", "entity_id": "binary_sensor.back", "equals": "on"},
                {"op": "entity_state", "entity_id": "binary_sensor.front", "equals": "on"},
            ],
        }
        self.assertEqual(extract_when_entity_ids(node), ["binary_sensor.back", "binary_sensor.front"])

    def test_any_recurses_like_all(self):
        node = {
            "op": "any",
            "children": [
                {"op": "entity_state", "entity_id": "a", "equals": "on"},
                {"op": "entity_state", "entity_id": "b", "equals": "on"},
            ],
        }
        self.assertEqual(extract_when_entity_ids(node), ["a", "b"])

    def test_duplicate_entity_ids_are_emitted_once(self):
        node = {
            "op": "any",
            "children": [
                {"op": "entity_state", "entity_id": "a", "equals": "on"},
                {"op": "entity_state", "entity_id": "a", "equals": "off"},
            ],
        }
        self.assertEqual(extract_when_entity_ids(node), ["a"])

    def test_not_recurses_into_child(self):
        node = {"op": "not", "child": {"op": "entity_state", "entity_id": "a", "equals": "on"}}
        self.assertEqual(extract_when_entity_ids(node), ["a"])

    def test_for_recurses_into_child(self):
        node = {
            "op": "for",
            "seconds": 30,
            "child": {"op": "entity_state", "entity_id": "a", "equals": "on"},
        }
        self.assertEqual(extract_when_entity_ids(node), ["a"])

    def test_non_entity_ops_yield_nothing(self):
        self.assertEqual(extract_when_entity_ids({"op": "time_in_range", "start": "08:00", "end": "10:00"}), [])
        self.assertEqual(extract_when_entity_ids({"op": "alarm_state_in", "states": ["armed_away"]}), [])
        self.assertEqual(
            extract_when_entity_ids(
                {
                    "op": "frigate_person_detected",
                    "cameras": ["front"],
                    "within_seconds": 60,
                    "min_confidence_pct": 70,
                }
            ),
            [],
        )

    def test_mixed_tree_only_emits_entity_state_refs(self):
        node = {
            "op": "all",
            "children": [
                {"op": "entity_state", "entity_id": "binary_sensor.back", "equals": "on"},
                {"op": "time_in_range", "start": "22:00", "end": "06:00"},
                {
                    "op": "not",
                    "child": {"op": "entity_state", "entity_id": "binary_sensor.front", "equals": "off"},
                },
                {"op": "alarm_state_in", "states": ["armed_away"]},
                {
                    "op": "for",
                    "seconds": 30,
                    "child": {"op": "entity_state", "entity_id": "binary_sensor.back", "equals": "on"},
                },
            ],
        }
        # 'binary_sensor.back' appears twice — emitted once. order = depth-first first-seen.
        self.assertEqual(
            extract_when_entity_ids(node),
            ["binary_sensor.back", "binary_sensor.front"],
        )

    def test_non_mapping_inputs_return_empty(self):
        self.assertEqual(extract_when_entity_ids(None), [])
        self.assertEqual(extract_when_entity_ids("entity_state"), [])
        self.assertEqual(extract_when_entity_ids(["op"]), [])
        self.assertEqual(extract_when_entity_ids({}), [])

    def test_unknown_op_yields_nothing(self):
        self.assertEqual(extract_when_entity_ids({"op": "totally_made_up"}), [])

    def test_malformed_children_are_ignored(self):
        node = {"op": "all", "children": "not-a-list"}
        self.assertEqual(extract_when_entity_ids(node), [])

        node = {"op": "all", "children": [None, "x", {"op": "entity_state", "entity_id": "a", "equals": "on"}]}
        self.assertEqual(extract_when_entity_ids(node), ["a"])
