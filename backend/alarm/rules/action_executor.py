from __future__ import annotations

from typing import Any

from alarm.state_machine import transitions as _transitions_module
from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway
from alarm.gateways.zigbee2mqtt import Zigbee2mqttGateway, default_zigbee2mqtt_gateway
from alarm.gateways.zwavejs import ZwavejsGateway, default_zwavejs_gateway
from alarm.models import Rule
from alarm.rules.action_handlers import ActionContext, AlarmServices, get_handler  # noqa: F401 — AlarmServices re-exported


def execute_actions(
    *,
    rule: Rule,
    actions: list[dict[str, Any]],
    now,
    actor_user=None,
    alarm_services: AlarmServices = _transitions_module,
    ha: HomeAssistantGateway = default_home_assistant_gateway,
    zwavejs: ZwavejsGateway = default_zwavejs_gateway,
    zigbee2mqtt: Zigbee2mqttGateway = default_zigbee2mqtt_gateway,
) -> dict[str, Any]:
    """Execute THEN actions for a rule, returning an audit-friendly result payload."""
    snapshot_before = alarm_services.get_current_snapshot(process_timers=True)
    alarm_state_before = snapshot_before.current_state
    action_results: list[dict[str, Any]] = []
    error_messages: list[str] = []

    ctx = ActionContext(
        rule=rule,
        actor_user=actor_user,
        alarm_services=alarm_services,
        ha=ha,
        zwavejs=zwavejs,
        zigbee2mqtt=zigbee2mqtt,
    )

    for action in actions:
        if not isinstance(action, dict):
            action_results.append({"ok": False, "error": "invalid_action"})
            continue

        action_type = action.get("type")
        handler = get_handler(action_type) if isinstance(action_type, str) else None
        if handler is None:
            action_results.append({"ok": False, "type": str(action_type), "error": "unsupported_action"})
            continue

        result, error = handler(action, ctx)
        action_results.append(result)
        if error is not None:
            error_messages.append(error)

    snapshot_after = alarm_services.get_current_snapshot(process_timers=True)
    return {
        "alarm_state_before": alarm_state_before,
        "alarm_state_after": snapshot_after.current_state,
        "actions": action_results,
        "errors": error_messages,
        "timestamp": now.isoformat(),
    }
