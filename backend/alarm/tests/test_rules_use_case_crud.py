from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from alarm.models import Rule
from alarm.use_cases.rules import create_rule, derive_kind_from_actions, update_rule


class DeriveKindFromActionsTests(TestCase):
    def test_alarm_trigger_action(self):
        definition = {"then": [{"type": "alarm_trigger"}]}
        self.assertEqual(derive_kind_from_actions(definition), "trigger")

    def test_alarm_disarm_action(self):
        definition = {"then": [{"type": "alarm_disarm"}]}
        self.assertEqual(derive_kind_from_actions(definition), "disarm")

    def test_alarm_arm_action(self):
        definition = {"then": [{"type": "alarm_arm"}]}
        self.assertEqual(derive_kind_from_actions(definition), "arm")

    def test_ha_call_service_defaults_to_trigger(self):
        definition = {"then": [{"type": "ha_call_service"}]}
        self.assertEqual(derive_kind_from_actions(definition), "trigger")

    def test_empty_then_defaults_to_trigger(self):
        self.assertEqual(derive_kind_from_actions({"then": []}), "trigger")
        self.assertEqual(derive_kind_from_actions({}), "trigger")

    def test_non_dict_definition_defaults_to_trigger(self):
        self.assertEqual(derive_kind_from_actions("bad"), "trigger")
        self.assertEqual(derive_kind_from_actions(None), "trigger")


MOCK_INVALIDATE = "alarm.use_cases.rules.invalidate_entity_rule_cache"
MOCK_SYNC = "alarm.use_cases.rules.sync_rule_entity_refs"
MOCK_EXTRACT_IDS = "alarm.use_cases.rules.extract_entity_ids_from_definition"
MOCK_EXTRACT_SOURCES = "alarm.use_cases.rules.extract_entity_sources_from_definition"


@patch(MOCK_SYNC)
@patch(MOCK_INVALIDATE)
@patch(MOCK_EXTRACT_IDS, return_value={"binary_sensor.front_door"})
@patch(MOCK_EXTRACT_SOURCES, return_value={"binary_sensor.front_door": "home_assistant"})
class CreateRuleTests(TestCase):
    def _make_definition(self):
        return {
            "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
            "then": [{"type": "alarm_trigger"}],
        }

    def test_auto_derives_kind_from_actions(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        definition = self._make_definition()
        rule = create_rule(
            validated_data={"name": "R1", "definition": definition},
            entity_ids=None,
        )
        self.assertEqual(rule.kind, "trigger")
        self.assertIsNotNone(rule.pk)

    def test_preserves_explicit_kind(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        definition = self._make_definition()
        rule = create_rule(
            validated_data={"name": "R2", "kind": "disarm", "definition": definition},
            entity_ids=None,
        )
        self.assertEqual(rule.kind, "disarm")

    def test_entity_ids_none_auto_extracts_from_definition(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        definition = self._make_definition()
        create_rule(validated_data={"name": "R3", "definition": definition}, entity_ids=None)
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args.kwargs
        self.assertEqual(call_kwargs["entity_ids"], ["binary_sensor.front_door"])

    def test_explicit_entity_ids_merged_with_extracted(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        definition = self._make_definition()
        create_rule(
            validated_data={"name": "R4", "definition": definition},
            entity_ids=["switch.light"],
        )
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args.kwargs
        self.assertEqual(call_kwargs["entity_ids"], ["binary_sensor.front_door", "switch.light"])

    def test_invalidates_cache(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        definition = self._make_definition()
        create_rule(validated_data={"name": "R5", "definition": definition}, entity_ids=None)
        mock_invalidate.assert_called_once()

    def test_passes_entity_sources_to_sync(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        definition = self._make_definition()
        create_rule(validated_data={"name": "R6", "definition": definition}, entity_ids=None)
        call_kwargs = mock_sync.call_args.kwargs
        self.assertEqual(call_kwargs["entity_sources"], {"binary_sensor.front_door": "home_assistant"})

    def test_empty_entity_ids_list_merges_with_extracted(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        definition = self._make_definition()
        create_rule(
            validated_data={"name": "R7", "definition": definition},
            entity_ids=[],
        )
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args.kwargs
        self.assertEqual(call_kwargs["entity_ids"], ["binary_sensor.front_door"])


@patch(MOCK_SYNC)
@patch(MOCK_INVALIDATE)
@patch(MOCK_EXTRACT_IDS, return_value={"binary_sensor.front_door"})
@patch(MOCK_EXTRACT_SOURCES, return_value={"binary_sensor.front_door": "home_assistant"})
class UpdateRuleTests(TestCase):
    def _create_existing_rule(self):
        return Rule.objects.create(
            name="Existing",
            kind="trigger",
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                "then": [{"type": "alarm_trigger"}],
            },
        )

    def test_definition_change_triggers_re_extraction(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        rule = self._create_existing_rule()
        new_definition = {
            "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "off"},
            "then": [{"type": "alarm_trigger"}],
        }
        update_rule(rule=rule, validated_data={"definition": new_definition}, entity_ids=None)
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args.kwargs
        self.assertEqual(call_kwargs["entity_ids"], ["binary_sensor.front_door"])

    def test_explicit_entity_ids_merged_with_extracted(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        rule = self._create_existing_rule()
        update_rule(
            rule=rule,
            validated_data={"definition": rule.definition},
            entity_ids=["switch.light"],
        )
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args.kwargs
        self.assertEqual(call_kwargs["entity_ids"], ["binary_sensor.front_door", "switch.light"])

    def test_no_definition_no_entity_ids_skips_sync(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        rule = self._create_existing_rule()
        update_rule(rule=rule, validated_data={"name": "Renamed"}, entity_ids=None)
        mock_sync.assert_not_called()

    def test_invalidates_cache_on_update(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        rule = self._create_existing_rule()
        update_rule(rule=rule, validated_data={"name": "Renamed"}, entity_ids=None)
        mock_invalidate.assert_called_once()

    def test_auto_derives_kind_on_update(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        rule = self._create_existing_rule()
        new_definition = {
            "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "off"},
            "then": [{"type": "alarm_disarm"}],
        }
        update_rule(rule=rule, validated_data={"definition": new_definition}, entity_ids=None)
        rule.refresh_from_db()
        self.assertEqual(rule.kind, "disarm")

    def test_preserves_explicit_kind_on_update(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        rule = self._create_existing_rule()
        update_rule(rule=rule, validated_data={"kind": "arm", "name": "Renamed"}, entity_ids=None)
        rule.refresh_from_db()
        self.assertEqual(rule.kind, "arm")

    def test_persists_attribute_changes(self, mock_sources, mock_ids, mock_invalidate, mock_sync):
        rule = self._create_existing_rule()
        update_rule(rule=rule, validated_data={"name": "Updated Name"}, entity_ids=None)
        rule.refresh_from_db()
        self.assertEqual(rule.name, "Updated Name")
