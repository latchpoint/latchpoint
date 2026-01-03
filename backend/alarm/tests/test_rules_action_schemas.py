"""
Tests for rules engine action schema validation and permissions.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from alarm.models import Rule
from alarm.rules.action_schemas import (
    ADMIN_ONLY_ACTION_TYPES,
    ACTION_TYPES,
    get_action_schemas,
    validate_action,
)
from alarm.serializers import RuleUpsertSerializer

User = get_user_model()


class ValidateActionTests(TestCase):
    """Tests for the validate_action function."""

    def test_valid_alarm_trigger(self):
        errors = validate_action({"type": "alarm_trigger"})
        self.assertEqual(errors, [])

    def test_valid_alarm_disarm(self):
        errors = validate_action({"type": "alarm_disarm"})
        self.assertEqual(errors, [])

    def test_valid_alarm_arm(self):
        errors = validate_action({"type": "alarm_arm", "mode": "armed_home"})
        self.assertEqual(errors, [])

    def test_valid_alarm_arm_all_modes(self):
        for mode in ("armed_home", "armed_away", "armed_night", "armed_vacation"):
            errors = validate_action({"type": "alarm_arm", "mode": mode})
            self.assertEqual(errors, [], f"Mode {mode} should be valid")

    def test_alarm_arm_missing_mode(self):
        errors = validate_action({"type": "alarm_arm"})
        self.assertTrue(any("mode" in e for e in errors))

    def test_alarm_arm_invalid_mode(self):
        errors = validate_action({"type": "alarm_arm", "mode": "invalid_mode"})
        self.assertTrue(any("Invalid mode" in e for e in errors))

    def test_valid_ha_call_service_minimal(self):
        errors = validate_action({
            "type": "ha_call_service",
            "action": "light.turn_on",
        })
        self.assertEqual(errors, [])

    def test_valid_ha_call_service_with_target_and_data(self):
        errors = validate_action({
            "type": "ha_call_service",
            "action": "lock.lock",
            "target": {"entity_id": ["lock.front_door"]},
            "data": {"code": "1234"},
        })
        self.assertEqual(errors, [])

    def test_ha_call_service_missing_action(self):
        errors = validate_action({
            "type": "ha_call_service",
        })
        self.assertTrue(any("action" in e for e in errors))

    def test_ha_call_service_invalid_action_format(self):
        errors = validate_action({
            "type": "ha_call_service",
            "action": "invalid_no_dot",
        })
        self.assertTrue(any("domain.service" in e for e in errors))

    def test_ha_call_service_invalid_target_type(self):
        errors = validate_action({
            "type": "ha_call_service",
            "action": "light.turn_on",
            "target": "not_an_object",
        })
        self.assertTrue(any("target" in e for e in errors))

    def test_ha_call_service_invalid_data_type(self):
        errors = validate_action({
            "type": "ha_call_service",
            "action": "light.turn_on",
            "data": "not_an_object",
        })
        self.assertTrue(any("data" in e for e in errors))

    def test_valid_zwavejs_set_value(self):
        errors = validate_action({
            "type": "zwavejs_set_value",
            "node_id": 12,
            "value_id": {
                "commandClass": 38,
                "property": "targetValue",
            },
            "value": 100,
        })
        self.assertEqual(errors, [])

    def test_valid_zwavejs_set_value_with_optional_fields(self):
        errors = validate_action({
            "type": "zwavejs_set_value",
            "node_id": 12,
            "value_id": {
                "commandClass": 38,
                "property": "targetValue",
                "endpoint": 1,
                "propertyKey": "some_key",
            },
            "value": True,
        })
        self.assertEqual(errors, [])

    def test_valid_zigbee2mqtt_set_value(self):
        errors = validate_action({
            "type": "zigbee2mqtt_set_value",
            "entity_id": "z2m_switch.0x00124b0018e2abcd_state",
            "value": True,
        })
        self.assertEqual(errors, [])

    def test_valid_zigbee2mqtt_switch(self):
        errors = validate_action({
            "type": "zigbee2mqtt_switch",
            "entity_id": "z2m_switch.0x00124b0018e2abcd_state",
            "state": "on",
        })
        self.assertEqual(errors, [])

    def test_zigbee2mqtt_switch_invalid_state(self):
        errors = validate_action({
            "type": "zigbee2mqtt_switch",
            "entity_id": "z2m_switch.0x00124b0018e2abcd_state",
            "state": "maybe",
        })
        self.assertTrue(any("state" in e for e in errors))

    def test_valid_zigbee2mqtt_light(self):
        errors = validate_action({
            "type": "zigbee2mqtt_light",
            "entity_id": "z2m_switch.0x00124b0018e2abcd_state",
            "state": "on",
            "brightness": 200,
        })
        self.assertEqual(errors, [])

    def test_zigbee2mqtt_light_invalid_brightness(self):
        errors = validate_action({
            "type": "zigbee2mqtt_light",
            "entity_id": "z2m_switch.0x00124b0018e2abcd_state",
            "state": "on",
            "brightness": "200",
        })
        self.assertTrue(any("brightness" in e for e in errors))

    def test_zigbee2mqtt_set_value_missing_entity_id(self):
        errors = validate_action({"type": "zigbee2mqtt_set_value", "value": True})
        self.assertTrue(any("entity_id" in e for e in errors))

    def test_zigbee2mqtt_set_value_missing_value(self):
        errors = validate_action({"type": "zigbee2mqtt_set_value", "entity_id": "z2m_switch.0x00124b0018e2abcd_state"})
        self.assertTrue(any("value" in e for e in errors))

    def test_zwavejs_set_value_missing_node_id(self):
        errors = validate_action({
            "type": "zwavejs_set_value",
            "value_id": {"commandClass": 38, "property": "targetValue"},
            "value": 100,
        })
        self.assertTrue(any("node_id" in e for e in errors))

    def test_zwavejs_set_value_missing_value_id(self):
        errors = validate_action({
            "type": "zwavejs_set_value",
            "node_id": 12,
            "value": 100,
        })
        self.assertTrue(any("value_id" in e for e in errors))

    def test_zwavejs_set_value_missing_value(self):
        errors = validate_action({
            "type": "zwavejs_set_value",
            "node_id": 12,
            "value_id": {"commandClass": 38, "property": "targetValue"},
        })
        self.assertTrue(any("value" in e for e in errors))

    def test_zwavejs_set_value_invalid_value_id_missing_command_class(self):
        errors = validate_action({
            "type": "zwavejs_set_value",
            "node_id": 12,
            "value_id": {"property": "targetValue"},
            "value": 100,
        })
        self.assertTrue(any("commandClass" in e for e in errors))

    def test_zwavejs_set_value_invalid_value_id_missing_property(self):
        errors = validate_action({
            "type": "zwavejs_set_value",
            "node_id": 12,
            "value_id": {"commandClass": 38},
            "value": 100,
        })
        self.assertTrue(any("property" in e for e in errors))

    def test_action_must_be_object(self):
        errors = validate_action("not_an_object")
        self.assertTrue(any("object" in e for e in errors))

    def test_action_must_have_type(self):
        errors = validate_action({"domain": "light"})
        self.assertTrue(any("type" in e for e in errors))

    def test_unknown_action_type(self):
        errors = validate_action({"type": "unknown_action"})
        self.assertTrue(any("Unknown action type" in e for e in errors))

    def test_unsupported_schema_version(self):
        errors = validate_action({"type": "alarm_trigger"}, schema_version=99)
        self.assertTrue(any("schema_version" in e for e in errors))


class ActionSchemaMetadataTests(TestCase):
    """Tests for action schema metadata."""

    def test_admin_only_actions(self):
        self.assertIn("ha_call_service", ADMIN_ONLY_ACTION_TYPES)
        self.assertIn("zwavejs_set_value", ADMIN_ONLY_ACTION_TYPES)
        self.assertIn("zigbee2mqtt_set_value", ADMIN_ONLY_ACTION_TYPES)
        self.assertIn("zigbee2mqtt_switch", ADMIN_ONLY_ACTION_TYPES)
        self.assertIn("zigbee2mqtt_light", ADMIN_ONLY_ACTION_TYPES)
        self.assertNotIn("alarm_trigger", ADMIN_ONLY_ACTION_TYPES)
        self.assertNotIn("alarm_disarm", ADMIN_ONLY_ACTION_TYPES)
        self.assertNotIn("alarm_arm", ADMIN_ONLY_ACTION_TYPES)

    def test_all_action_types_defined(self):
        self.assertEqual(ACTION_TYPES, {
            "alarm_trigger",
            "alarm_disarm",
            "alarm_arm",
            "ha_call_service",
            "zwavejs_set_value",
            "zigbee2mqtt_set_value",
            "zigbee2mqtt_switch",
            "zigbee2mqtt_light",
            "send_notification",
        })

    def test_get_action_schemas_returns_all_types(self):
        schemas = get_action_schemas()
        self.assertEqual(set(schemas.keys()), ACTION_TYPES)

    def test_get_action_schemas_includes_admin_only_flag(self):
        schemas = get_action_schemas()
        self.assertFalse(schemas["alarm_trigger"]["admin_only"])
        self.assertFalse(schemas["alarm_disarm"]["admin_only"])
        self.assertFalse(schemas["alarm_arm"]["admin_only"])
        self.assertTrue(schemas["ha_call_service"]["admin_only"])
        self.assertTrue(schemas["zwavejs_set_value"]["admin_only"])
        self.assertTrue(schemas["zigbee2mqtt_set_value"]["admin_only"])
        self.assertTrue(schemas["zigbee2mqtt_switch"]["admin_only"])
        self.assertTrue(schemas["zigbee2mqtt_light"]["admin_only"])


class RuleUpsertSerializerValidationTests(TestCase):
    """Tests for rule serializer validation of definition.then."""

    def setUp(self):
        self.user = User.objects.create_user(email="test@test.com", password="testpass")
        self.admin_user = User.objects.create_superuser(email="admin@test.com", password="adminpass")
        self.factory = APIRequestFactory()

    def _make_request(self, user):
        request = self.factory.post("/fake/")
        request.user = user
        return request

    def test_valid_then_actions_accepted(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {"type": "alarm_trigger"},
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_invalid_then_action_rejected(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {"type": "alarm_arm"},  # Missing mode
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("definition", serializer.errors)

    def test_then_must_be_list(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": {"type": "alarm_trigger"},  # Object instead of list
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("definition", serializer.errors)

    def test_empty_then_list_accepted(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_multiple_valid_actions_accepted(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {"type": "alarm_trigger"},
                    {"type": "ha_call_service", "action": "light.turn_on"},
                    {"type": "alarm_disarm"},
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)


class RuleUpsertSerializerPermissionTests(TestCase):
    """Tests for admin-only action permission enforcement."""

    def setUp(self):
        self.user = User.objects.create_user(email="test@test.com", password="testpass")
        self.admin_user = User.objects.create_superuser(email="admin@test.com", password="adminpass")
        self.staff_user = User.objects.create_user(email="staff@test.com", password="staffpass", is_staff=True)
        self.factory = APIRequestFactory()

    def _make_request(self, user):
        request = self.factory.post("/fake/")
        request.user = user
        return request

    def test_non_admin_can_create_rule_with_alarm_actions(self):
        request = self._make_request(self.user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {"type": "alarm_trigger"},
                    {"type": "alarm_arm", "mode": "armed_home"},
                    {"type": "alarm_disarm"},
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_non_admin_cannot_use_ha_call_service(self):
        request = self._make_request(self.user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {"type": "ha_call_service", "action": "light.turn_on"},
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("definition", serializer.errors)

    def test_non_admin_cannot_use_zwavejs_set_value(self):
        request = self._make_request(self.user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zwavejs_set_value",
                        "node_id": 12,
                        "value_id": {"commandClass": 38, "property": "targetValue"},
                        "value": 100,
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("definition", serializer.errors)

    def test_non_admin_cannot_use_zigbee2mqtt_set_value(self):
        request = self._make_request(self.user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zigbee2mqtt_set_value",
                        "entity_id": "z2m_switch.0x00124b_state",
                        "value": True,
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("definition", serializer.errors)

    def test_non_admin_cannot_use_zigbee2mqtt_switch(self):
        request = self._make_request(self.user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zigbee2mqtt_switch",
                        "entity_id": "z2m_switch.0x00124b_state",
                        "state": "on",
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("definition", serializer.errors)

    def test_non_admin_cannot_use_zigbee2mqtt_light(self):
        request = self._make_request(self.user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zigbee2mqtt_light",
                        "entity_id": "z2m_switch.0x00124b_state",
                        "state": "on",
                        "brightness": 100,
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertFalse(serializer.is_valid())
        self.assertIn("definition", serializer.errors)

    def test_admin_can_use_ha_call_service(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {"type": "ha_call_service", "action": "light.turn_on"},
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_admin_can_use_zwavejs_set_value(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zwavejs_set_value",
                        "node_id": 12,
                        "value_id": {"commandClass": 38, "property": "targetValue"},
                        "value": 100,
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_admin_can_use_zigbee2mqtt_set_value(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zigbee2mqtt_set_value",
                        "entity_id": "z2m_switch.0x00124b_state",
                        "value": True,
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_admin_can_use_zigbee2mqtt_switch(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zigbee2mqtt_switch",
                        "entity_id": "z2m_switch.0x00124b_state",
                        "state": "off",
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_admin_can_use_zigbee2mqtt_light(self):
        request = self._make_request(self.admin_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {
                        "type": "zigbee2mqtt_light",
                        "entity_id": "z2m_switch.0x00124b_state",
                        "state": "on",
                        "brightness": 200,
                    },
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_staff_user_can_use_admin_actions(self):
        request = self._make_request(self.staff_user)
        data = {
            "name": "Test Rule",
            "kind": "trigger",
            "definition": {
                "when": {"op": "entity_state", "entity_id": "binary_sensor.test", "equals": "on"},
                "then": [
                    {"type": "ha_call_service", "action": "lock.lock"},
                ],
            },
        }
        serializer = RuleUpsertSerializer(data=data, context={"request": request})
        self.assertTrue(serializer.is_valid(), serializer.errors)


class SupportedActionsEndpointTests(TestCase):
    """Tests for the supported-actions discovery endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(email="test@test.com", password="testpass")
        self.admin_user = User.objects.create_superuser(email="admin@test.com", password="adminpass")

    def test_non_admin_sees_only_non_admin_actions(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/alarm/rules/supported-actions/")
        self.assertEqual(response.status_code, 200)

        action_types = {a["type"] for a in response.json()["data"]["actions"]}
        self.assertIn("alarm_trigger", action_types)
        self.assertIn("alarm_disarm", action_types)
        self.assertIn("alarm_arm", action_types)
        self.assertNotIn("ha_call_service", action_types)
        self.assertNotIn("zwavejs_set_value", action_types)
        self.assertNotIn("zigbee2mqtt_set_value", action_types)
        self.assertNotIn("zigbee2mqtt_switch", action_types)
        self.assertNotIn("zigbee2mqtt_light", action_types)

    def test_admin_sees_all_actions(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/api/alarm/rules/supported-actions/")
        self.assertEqual(response.status_code, 200)

        action_types = {a["type"] for a in response.json()["data"]["actions"]}
        self.assertEqual(action_types, ACTION_TYPES)

    def test_response_includes_schema_version(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/api/alarm/rules/supported-actions/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["schema_version"], 1)

    def test_response_includes_admin_only_flag(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/api/alarm/rules/supported-actions/")
        self.assertEqual(response.status_code, 200)

        actions_by_type = {a["type"]: a for a in response.json()["data"]["actions"]}
        self.assertFalse(actions_by_type["alarm_trigger"]["admin_only"])
        self.assertTrue(actions_by_type["ha_call_service"]["admin_only"])
        self.assertTrue(actions_by_type["zigbee2mqtt_set_value"]["admin_only"])
        self.assertTrue(actions_by_type["zigbee2mqtt_switch"]["admin_only"])
        self.assertTrue(actions_by_type["zigbee2mqtt_light"]["admin_only"])

    def test_response_includes_schema_for_each_action(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/api/alarm/rules/supported-actions/")
        self.assertEqual(response.status_code, 200)

        for action in response.json()["data"]["actions"]:
            self.assertIn("schema", action)
            self.assertIn("type", action["schema"])
            self.assertIn("properties", action["schema"])
            self.assertIn("required", action["schema"])
