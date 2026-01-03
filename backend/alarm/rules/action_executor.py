from __future__ import annotations

from typing import Any, Protocol

from alarm import services
from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway
from alarm.gateways.zigbee2mqtt import Zigbee2mqttGateway, default_zigbee2mqtt_gateway
from alarm.gateways.zwavejs import ZwavejsGateway, default_zwavejs_gateway
from alarm.models import Rule
from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
from notifications.dispatcher import get_dispatcher as get_notification_dispatcher


class AlarmServices(Protocol):
    def get_current_snapshot(self, *, process_timers: bool):
        """Return the current alarm snapshot, optionally processing timers."""

        ...

    def disarm(self, *, user=None, code=None, reason: str = ""):
        """Disarm the alarm."""

        ...

    def arm(self, *, target_state: str, user=None, code=None, reason: str = ""):
        """Arm the alarm to the target state."""

        ...

    def trigger(self, *, user=None, reason: str = ""):
        """Force the alarm into triggered state."""

        ...


def execute_actions(
    *,
    rule: Rule,
    actions: list[dict[str, Any]],
    now,
    actor_user=None,
    alarm_services: AlarmServices = services,
    ha: HomeAssistantGateway = default_home_assistant_gateway,
    zwavejs: ZwavejsGateway = default_zwavejs_gateway,
    zigbee2mqtt: Zigbee2mqttGateway = default_zigbee2mqtt_gateway,
) -> dict[str, Any]:
    """Execute THEN actions for a rule, returning an audit-friendly result payload."""
    snapshot_before = alarm_services.get_current_snapshot(process_timers=True)
    alarm_state_before = snapshot_before.current_state
    action_results: list[dict[str, Any]] = []
    error_messages: list[str] = []

    for action in actions:
        if not isinstance(action, dict):
            action_results.append({"ok": False, "error": "invalid_action"})
            continue
        action_type = action.get("type")
        if action_type == "alarm_disarm":
            try:
                alarm_services.disarm(user=actor_user, reason=f"rule:{rule.id}")
                action_results.append({"ok": True, "type": "alarm_disarm"})
            except Exception as exc:  # pragma: no cover - defensive
                action_results.append({"ok": False, "type": "alarm_disarm", "error": str(exc)})
                error_messages.append(str(exc))
            continue

        if action_type == "alarm_arm":
            mode = action.get("mode")
            if not isinstance(mode, str):
                action_results.append({"ok": False, "type": "alarm_arm", "error": "missing_mode"})
                continue
            try:
                alarm_services.arm(target_state=mode, user=actor_user, reason=f"rule:{rule.id}")
                action_results.append({"ok": True, "type": "alarm_arm", "mode": mode})
            except Exception as exc:
                action_results.append({"ok": False, "type": "alarm_arm", "mode": mode, "error": str(exc)})
                error_messages.append(str(exc))
            continue

        if action_type == "alarm_trigger":
            try:
                alarm_services.trigger(user=actor_user, reason=f"rule:{rule.id}")
                action_results.append({"ok": True, "type": "alarm_trigger"})
            except Exception as exc:
                action_results.append({"ok": False, "type": "alarm_trigger", "error": str(exc)})
                error_messages.append(str(exc))
            continue

        if action_type == "ha_call_service":
            # Parse action field (e.g., "light.turn_on" -> domain="light", service="turn_on")
            action_str = action.get("action")
            if not isinstance(action_str, str) or "." not in action_str:
                action_results.append({"ok": False, "type": "ha_call_service", "error": "invalid_action_format"})
                continue
            domain, service_name = action_str.split(".", 1)
            target = action.get("target")
            data = action.get("data")
            try:
                ha.call_service(
                    domain=domain,
                    service=service_name,
                    target=target if isinstance(target, dict) else None,
                    service_data=data if isinstance(data, dict) else None,
                )
                action_results.append(
                    {"ok": True, "type": "ha_call_service", "action": action_str}
                )
            except Exception as exc:
                action_results.append(
                    {
                        "ok": False,
                        "type": "ha_call_service",
                        "action": action_str,
                        "error": str(exc),
                    }
                )
                error_messages.append(str(exc))
            continue

        if action_type == "zwavejs_set_value":
            node_id = action.get("node_id")
            value_id = action.get("value_id")
            value = action.get("value")
            if not isinstance(node_id, int) or not isinstance(value_id, dict):
                action_results.append({"ok": False, "type": "zwavejs_set_value", "error": "missing_node_id_or_value_id"})
                continue
            command_class = value_id.get("commandClass")
            endpoint = value_id.get("endpoint", 0)
            prop = value_id.get("property")
            prop_key = value_id.get("propertyKey")
            if not isinstance(command_class, int) or not isinstance(endpoint, int) or prop is None:
                action_results.append({"ok": False, "type": "zwavejs_set_value", "error": "invalid_value_id"})
                continue
            try:
                profile = get_active_settings_profile()
                settings_obj = get_setting_json(profile, "zwavejs_connection") or {}
                if not isinstance(settings_obj, dict):
                    settings_obj = {}
                zwavejs.apply_settings(settings_obj=settings_obj)
                zwavejs.ensure_connected(timeout_seconds=float(settings_obj.get("connect_timeout_seconds") or 2))
                zwavejs.set_value(
                    node_id=node_id,
                    endpoint=endpoint,
                    command_class=command_class,
                    property=prop,
                    property_key=prop_key if isinstance(prop_key, (str, int)) else None,
                    value=value,
                )
                action_results.append({"ok": True, "type": "zwavejs_set_value", "node_id": node_id, "value_id": value_id})
            except Exception as exc:
                action_results.append(
                    {"ok": False, "type": "zwavejs_set_value", "node_id": node_id, "value_id": value_id, "error": str(exc)}
                )
                error_messages.append(str(exc))
            continue

        if action_type == "zigbee2mqtt_set_value":
            entity_id = action.get("entity_id")
            if not isinstance(entity_id, str) or not entity_id.strip():
                action_results.append({"ok": False, "type": "zigbee2mqtt_set_value", "error": "missing_entity_id"})
                continue
            if "value" not in action:
                action_results.append({"ok": False, "type": "zigbee2mqtt_set_value", "entity_id": entity_id, "error": "missing_value"})
                continue
            try:
                zigbee2mqtt.set_entity_value(entity_id=entity_id.strip(), value=action.get("value"))
                action_results.append({"ok": True, "type": "zigbee2mqtt_set_value", "entity_id": entity_id.strip()})
            except Exception as exc:
                action_results.append({"ok": False, "type": "zigbee2mqtt_set_value", "entity_id": entity_id.strip(), "error": str(exc)})
                error_messages.append(str(exc))
            continue

        if action_type == "zigbee2mqtt_switch":
            entity_id = action.get("entity_id")
            state = action.get("state")
            if not isinstance(entity_id, str) or not entity_id.strip():
                action_results.append({"ok": False, "type": "zigbee2mqtt_switch", "error": "missing_entity_id"})
                continue
            if state not in ("on", "off"):
                action_results.append({"ok": False, "type": "zigbee2mqtt_switch", "entity_id": entity_id.strip(), "error": "invalid_state"})
                continue
            try:
                zigbee2mqtt.set_entity_value(entity_id=entity_id.strip(), value={"state": state == "on"})
                action_results.append({"ok": True, "type": "zigbee2mqtt_switch", "entity_id": entity_id.strip(), "state": state})
            except Exception as exc:
                action_results.append(
                    {"ok": False, "type": "zigbee2mqtt_switch", "entity_id": entity_id.strip(), "state": state, "error": str(exc)}
                )
                error_messages.append(str(exc))
            continue

        if action_type == "zigbee2mqtt_light":
            entity_id = action.get("entity_id")
            state = action.get("state")
            brightness = action.get("brightness")
            if not isinstance(entity_id, str) or not entity_id.strip():
                action_results.append({"ok": False, "type": "zigbee2mqtt_light", "error": "missing_entity_id"})
                continue
            if state not in ("on", "off"):
                action_results.append({"ok": False, "type": "zigbee2mqtt_light", "entity_id": entity_id.strip(), "error": "invalid_state"})
                continue
            if brightness is not None and not isinstance(brightness, int):
                action_results.append({"ok": False, "type": "zigbee2mqtt_light", "entity_id": entity_id.strip(), "error": "invalid_brightness"})
                continue

            payload: dict[str, Any] = {"state": state == "on"}
            if brightness is not None:
                payload["brightness"] = brightness
            try:
                zigbee2mqtt.set_entity_value(entity_id=entity_id.strip(), value=payload)
                action_results.append(
                    {
                        "ok": True,
                        "type": "zigbee2mqtt_light",
                        "entity_id": entity_id.strip(),
                        "state": state,
                        **({"brightness": brightness} if brightness is not None else {}),
                    }
                )
            except Exception as exc:
                action_results.append(
                    {
                        "ok": False,
                        "type": "zigbee2mqtt_light",
                        "entity_id": entity_id.strip(),
                        "state": state,
                        **({"brightness": brightness} if brightness is not None else {}),
                        "error": str(exc),
                    }
                )
                error_messages.append(str(exc))
            continue

        if action_type == "send_notification":
            provider_id = action.get("provider_id")
            message = action.get("message")
            title = action.get("title")
            data = action.get("data")

            if not isinstance(provider_id, str) or not provider_id:
                action_results.append({"ok": False, "type": "send_notification", "error": "missing_provider_id"})
                continue
            if not isinstance(message, str) or not message:
                action_results.append({"ok": False, "type": "send_notification", "error": "missing_message"})
                continue

            try:
                dispatcher = get_notification_dispatcher()
                profile = get_active_settings_profile()
                delivery, enqueue_result = dispatcher.enqueue(
                    profile=profile,
                    provider_id=provider_id,
                    message=message,
                    title=title if isinstance(title, str) else None,
                    data=data if isinstance(data, dict) else None,
                    rule_name=rule.name,
                )
                if delivery:
                    action_results.append({
                        "ok": True,
                        "type": "send_notification",
                        "provider_id": provider_id,
                        "delivery_id": str(delivery.id),
                        "queued": True,
                    })
                else:
                    action_results.append({
                        "ok": False,
                        "type": "send_notification",
                        "provider_id": provider_id,
                        "error": enqueue_result.message,
                        "error_code": enqueue_result.error_code,
                    })
                    error_messages.append(enqueue_result.message)
            except Exception as exc:
                action_results.append({
                    "ok": False,
                    "type": "send_notification",
                    "provider_id": provider_id,
                    "error": str(exc),
                })
                error_messages.append(str(exc))
            continue

        action_results.append({"ok": False, "type": str(action_type), "error": "unsupported_action"})

    snapshot_after = alarm_services.get_current_snapshot(process_timers=True)
    return {
        "alarm_state_before": alarm_state_before,
        "alarm_state_after": snapshot_after.current_state,
        "actions": action_results,
        "errors": error_messages,
        "timestamp": now.isoformat(),
    }
