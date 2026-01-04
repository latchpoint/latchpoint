"""Tests for entity ID extraction from rule definitions."""

from unittest import TestCase

from alarm.dispatcher.entity_extractor import extract_entity_ids_from_definition


class TestExtractEntityIds(TestCase):
    """Tests for extract_entity_ids_from_definition function."""

    def test_empty_definition_returns_empty_set(self):
        """Empty or invalid definition returns empty set."""
        self.assertEqual(extract_entity_ids_from_definition(None), set())
        self.assertEqual(extract_entity_ids_from_definition({}), set())
        self.assertEqual(extract_entity_ids_from_definition({"then": []}), set())

    def test_entity_state_op_extracts_entity_id(self):
        """entity_state operator extracts the entity_id."""
        definition = {
            "when": {
                "op": "entity_state",
                "entity_id": "binary_sensor.front_door",
                "equals": "on",
            },
            "then": [{"type": "alarm_trigger"}],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"binary_sensor.front_door"})

    def test_all_op_extracts_from_children(self):
        """all operator extracts from all children."""
        definition = {
            "when": {
                "op": "all",
                "children": [
                    {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                    {"op": "entity_state", "entity_id": "binary_sensor.back_door", "equals": "on"},
                ],
            },
            "then": [{"type": "alarm_trigger"}],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"binary_sensor.front_door", "binary_sensor.back_door"})

    def test_any_op_extracts_from_children(self):
        """any operator extracts from all children."""
        definition = {
            "when": {
                "op": "any",
                "children": [
                    {"op": "entity_state", "entity_id": "binary_sensor.motion_1", "equals": "on"},
                    {"op": "entity_state", "entity_id": "binary_sensor.motion_2", "equals": "on"},
                ],
            },
            "then": [{"type": "alarm_trigger"}],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"binary_sensor.motion_1", "binary_sensor.motion_2"})

    def test_not_op_extracts_from_child(self):
        """not operator extracts from its child."""
        definition = {
            "when": {
                "op": "not",
                "child": {"op": "entity_state", "entity_id": "binary_sensor.window", "equals": "open"},
            },
            "then": [{"type": "alarm_arm"}],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"binary_sensor.window"})

    def test_for_op_extracts_from_child(self):
        """for operator extracts from its child."""
        definition = {
            "when": {
                "op": "for",
                "seconds": 30,
                "child": {"op": "entity_state", "entity_id": "binary_sensor.entry", "equals": "on"},
            },
            "then": [{"type": "alarm_trigger"}],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"binary_sensor.entry"})

    def test_nested_operators(self):
        """Deeply nested operators extract all entity_ids."""
        definition = {
            "when": {
                "op": "for",
                "seconds": 10,
                "child": {
                    "op": "all",
                    "children": [
                        {"op": "entity_state", "entity_id": "sensor.a", "equals": "1"},
                        {
                            "op": "any",
                            "children": [
                                {"op": "entity_state", "entity_id": "sensor.b", "equals": "2"},
                                {
                                    "op": "not",
                                    "child": {"op": "entity_state", "entity_id": "sensor.c", "equals": "3"},
                                },
                            ],
                        },
                    ],
                },
            },
            "then": [],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"sensor.a", "sensor.b", "sensor.c"})

    def test_non_entity_ops_ignored(self):
        """Non-entity operators (alarm_state_in, frigate_detection) are ignored."""
        definition = {
            "when": {
                "op": "all",
                "children": [
                    {"op": "alarm_state_in", "states": ["armed_home", "armed_away"]},
                    {"op": "frigate_detection", "camera": "front", "label": "person"},
                    {"op": "entity_state", "entity_id": "sensor.real", "equals": "on"},
                ],
            },
            "then": [],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"sensor.real"})

    def test_whitespace_trimmed(self):
        """Entity IDs have whitespace trimmed."""
        definition = {
            "when": {
                "op": "entity_state",
                "entity_id": "  sensor.trimmed  ",
                "equals": "on",
            },
            "then": [],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"sensor.trimmed"})

    def test_empty_entity_id_skipped(self):
        """Empty entity_ids are skipped."""
        definition = {
            "when": {
                "op": "all",
                "children": [
                    {"op": "entity_state", "entity_id": "", "equals": "on"},
                    {"op": "entity_state", "entity_id": "   ", "equals": "on"},
                    {"op": "entity_state", "entity_id": "sensor.valid", "equals": "on"},
                ],
            },
            "then": [],
        }
        result = extract_entity_ids_from_definition(definition)
        self.assertEqual(result, {"sensor.valid"})
