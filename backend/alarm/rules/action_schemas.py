"""
Action schema definitions and validation for rules engine THEN actions.

Supports schema_version=1 action types:
- alarm_trigger: Trigger the alarm
- alarm_disarm: Disarm the alarm
- alarm_arm: Arm the alarm with a target mode
- ha_call_service: Call a Home Assistant service
- zwavejs_set_value: Write a Z-Wave JS value
- zigbee2mqtt_set_value: Publish a Zigbee2MQTT set payload for an entity
- zigbee2mqtt_switch: Zigbee2MQTT switch on/off (guided)
- zigbee2mqtt_light: Zigbee2MQTT light on/off + brightness (guided)
- send_notification: Send a notification via configured provider
"""
from __future__ import annotations

from typing import Any

ARMED_MODES = ("armed_home", "armed_away", "armed_night", "armed_vacation")

ADMIN_ONLY_ACTION_TYPES = frozenset({
    "ha_call_service",
    "zwavejs_set_value",
    "zigbee2mqtt_set_value",
    "zigbee2mqtt_switch",
    "zigbee2mqtt_light",
})

ACTION_TYPES = frozenset({
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

ZIGBEE2MQTT_ON_OFF = ("on", "off")


def validate_action(action: Any, schema_version: int = 1) -> list[str]:
    """
    Validate an action object against the schema for the given version.

    Returns a list of error messages. Empty list means valid.
    """
    if schema_version != 1:
        return [f"Unsupported schema_version: {schema_version}"]

    if not isinstance(action, dict):
        return ["Action must be an object"]

    action_type = action.get("type")
    if not isinstance(action_type, str):
        return ["Action must have a 'type' string field"]

    if action_type not in ACTION_TYPES:
        return [f"Unknown action type: {action_type}"]

    validator = _VALIDATORS.get(action_type)
    if validator:
        return validator(action)

    return []


def _validate_alarm_trigger(action: dict[str, Any]) -> list[str]:
    """alarm_trigger requires no additional fields."""
    return []


def _validate_alarm_disarm(action: dict[str, Any]) -> list[str]:
    """alarm_disarm requires no additional fields."""
    return []


def _validate_alarm_arm(action: dict[str, Any]) -> list[str]:
    """alarm_arm requires a valid 'mode' field."""
    errors: list[str] = []
    mode = action.get("mode")
    if not isinstance(mode, str):
        errors.append("alarm_arm requires 'mode' string field")
    elif mode not in ARMED_MODES:
        errors.append(f"Invalid mode '{mode}'. Must be one of: {', '.join(ARMED_MODES)}")
    return errors


def _validate_ha_call_service(action: dict[str, Any]) -> list[str]:
    """ha_call_service requires 'action' string in domain.service format (e.g., 'light.turn_on')."""
    errors: list[str] = []
    action_str = action.get("action")

    if not isinstance(action_str, str) or not action_str:
        errors.append("ha_call_service requires 'action' string field (e.g., 'light.turn_on')")
    elif "." not in action_str:
        errors.append("ha_call_service 'action' must be in domain.service format (e.g., 'light.turn_on')")

    target = action.get("target")
    if target is not None and not isinstance(target, dict):
        errors.append("ha_call_service 'target' must be an object if provided")

    data = action.get("data")
    if data is not None and not isinstance(data, dict):
        errors.append("ha_call_service 'data' must be an object if provided")

    return errors


def _validate_zwavejs_set_value(action: dict[str, Any]) -> list[str]:
    """zwavejs_set_value requires node_id (int), value_id (object), and value."""
    errors: list[str] = []

    node_id = action.get("node_id")
    if not isinstance(node_id, int):
        errors.append("zwavejs_set_value requires 'node_id' integer field")

    value_id = action.get("value_id")
    if not isinstance(value_id, dict):
        errors.append("zwavejs_set_value requires 'value_id' object field")
    else:
        command_class = value_id.get("commandClass")
        if not isinstance(command_class, int):
            errors.append("value_id.commandClass must be an integer")

        prop = value_id.get("property")
        if not isinstance(prop, (str, int)):
            errors.append("value_id.property must be a string or integer")

        endpoint = value_id.get("endpoint")
        if endpoint is not None and not isinstance(endpoint, int):
            errors.append("value_id.endpoint must be an integer if provided")

        property_key = value_id.get("propertyKey")
        if property_key is not None and not isinstance(property_key, (str, int)):
            errors.append("value_id.propertyKey must be a string or integer if provided")

    if "value" not in action:
        errors.append("zwavejs_set_value requires 'value' field")

    return errors


def _validate_zigbee2mqtt_set_value(action: dict[str, Any]) -> list[str]:
    """zigbee2mqtt_set_value requires entity_id (string) and value."""
    errors: list[str] = []

    entity_id = action.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id.strip():
        errors.append("zigbee2mqtt_set_value requires 'entity_id' string field")

    if "value" not in action:
        errors.append("zigbee2mqtt_set_value requires 'value' field")

    return errors


def _validate_zigbee2mqtt_switch(action: dict[str, Any]) -> list[str]:
    """zigbee2mqtt_switch requires entity_id (string) and state ('on'|'off')."""
    errors: list[str] = []
    entity_id = action.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id.strip():
        errors.append("zigbee2mqtt_switch requires 'entity_id' string field")
    state = action.get("state")
    if not isinstance(state, str) or state not in ZIGBEE2MQTT_ON_OFF:
        errors.append("zigbee2mqtt_switch requires 'state' field of 'on' or 'off'")
    return errors


def _validate_zigbee2mqtt_light(action: dict[str, Any]) -> list[str]:
    """zigbee2mqtt_light requires entity_id (string), state ('on'|'off'), and optional brightness (0-255)."""
    errors: list[str] = []
    entity_id = action.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id.strip():
        errors.append("zigbee2mqtt_light requires 'entity_id' string field")
    state = action.get("state")
    if not isinstance(state, str) or state not in ZIGBEE2MQTT_ON_OFF:
        errors.append("zigbee2mqtt_light requires 'state' field of 'on' or 'off'")
    brightness = action.get("brightness")
    if brightness is not None:
        if not isinstance(brightness, int):
            errors.append("zigbee2mqtt_light 'brightness' must be an integer if provided")
        elif brightness < 0 or brightness > 255:
            errors.append("zigbee2mqtt_light 'brightness' must be between 0 and 255")
    return errors


def _validate_send_notification(action: dict[str, Any]) -> list[str]:
    """send_notification requires provider_id (UUID) and message (string)."""
    errors: list[str] = []

    provider_id = action.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id:
        errors.append("send_notification requires 'provider_id' string field")

    message = action.get("message")
    if not isinstance(message, str) or not message:
        errors.append("send_notification requires 'message' string field")

    title = action.get("title")
    if title is not None and not isinstance(title, str):
        errors.append("send_notification 'title' must be a string if provided")

    data = action.get("data")
    if data is not None and not isinstance(data, dict):
        errors.append("send_notification 'data' must be an object if provided")

    return errors


_VALIDATORS = {
    "alarm_trigger": _validate_alarm_trigger,
    "alarm_disarm": _validate_alarm_disarm,
    "alarm_arm": _validate_alarm_arm,
    "ha_call_service": _validate_ha_call_service,
    "zwavejs_set_value": _validate_zwavejs_set_value,
    "zigbee2mqtt_set_value": _validate_zigbee2mqtt_set_value,
    "zigbee2mqtt_switch": _validate_zigbee2mqtt_switch,
    "zigbee2mqtt_light": _validate_zigbee2mqtt_light,
    "send_notification": _validate_send_notification,
}


def get_action_schemas() -> dict[str, dict[str, Any]]:
    """
    Return the canonical action schemas for frontend discovery.
    """
    return {
        "alarm_trigger": {
            "type": "object",
            "properties": {
                "type": {"const": "alarm_trigger"},
            },
            "required": ["type"],
            "admin_only": False,
        },
        "alarm_disarm": {
            "type": "object",
            "properties": {
                "type": {"const": "alarm_disarm"},
            },
            "required": ["type"],
            "admin_only": False,
        },
        "alarm_arm": {
            "type": "object",
            "properties": {
                "type": {"const": "alarm_arm"},
                "mode": {"type": "string", "enum": list(ARMED_MODES)},
            },
            "required": ["type", "mode"],
            "admin_only": False,
        },
        "ha_call_service": {
            "type": "object",
            "properties": {
                "type": {"const": "ha_call_service"},
                "action": {"type": "string", "description": "Home Assistant action in domain.service format (e.g., 'light.turn_on')"},
                "target": {"type": "object"},
                "data": {"type": "object"},
            },
            "required": ["type", "action"],
            "admin_only": True,
        },
        "zwavejs_set_value": {
            "type": "object",
            "properties": {
                "type": {"const": "zwavejs_set_value"},
                "node_id": {"type": "integer"},
                "value_id": {
                    "type": "object",
                    "properties": {
                        "commandClass": {"type": "integer"},
                        "property": {"type": ["string", "integer"]},
                        "endpoint": {"type": "integer"},
                        "propertyKey": {"type": ["string", "integer"]},
                    },
                    "required": ["commandClass", "property"],
                },
                "value": {},
            },
            "required": ["type", "node_id", "value_id", "value"],
            "admin_only": True,
        },
        "zigbee2mqtt_set_value": {
            "type": "object",
            "properties": {
                "type": {"const": "zigbee2mqtt_set_value"},
                "entity_id": {"type": "string", "description": "Target Zigbee2MQTT entity_id (e.g., 'z2m_switch.0x..._state')"},
                "value": {},
            },
            "required": ["type", "entity_id", "value"],
            "admin_only": True,
        },
        "zigbee2mqtt_switch": {
            "type": "object",
            "properties": {
                "type": {"const": "zigbee2mqtt_switch"},
                "entity_id": {"type": "string", "description": "Any Zigbee2MQTT entity_id for the target device"},
                "state": {"type": "string", "enum": list(ZIGBEE2MQTT_ON_OFF)},
            },
            "required": ["type", "entity_id", "state"],
            "admin_only": True,
        },
        "zigbee2mqtt_light": {
            "type": "object",
            "properties": {
                "type": {"const": "zigbee2mqtt_light"},
                "entity_id": {"type": "string", "description": "Any Zigbee2MQTT entity_id for the target device"},
                "state": {"type": "string", "enum": list(ZIGBEE2MQTT_ON_OFF)},
                "brightness": {"type": "integer", "minimum": 0, "maximum": 255},
            },
            "required": ["type", "entity_id", "state"],
            "admin_only": True,
        },
        "send_notification": {
            "type": "object",
            "properties": {
                "type": {"const": "send_notification"},
                "provider_id": {"type": "string", "format": "uuid", "description": "UUID of the notification provider"},
                "message": {"type": "string", "description": "Notification message body"},
                "title": {"type": "string", "description": "Optional notification title"},
                "data": {"type": "object", "description": "Optional provider-specific data"},
            },
            "required": ["type", "provider_id", "message"],
            "admin_only": False,
        },
    }
