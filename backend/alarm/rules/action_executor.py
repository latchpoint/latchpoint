from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway
from alarm.gateways.zigbee2mqtt import Zigbee2mqttGateway, default_zigbee2mqtt_gateway
from alarm.gateways.zwavejs import ZwavejsGateway, default_zwavejs_gateway
from alarm.models import Rule
from alarm.rules.action_handlers import (  # noqa: F401 — AlarmServices re-exported
    ActionContext,
    AlarmServices,
    get_handler,
)
from alarm.rules.pending_actions import enqueue_pending_action
from alarm.rules.template_render import TriggerContext
from alarm.state_machine import transitions as _transitions_module

logger = logging.getLogger(__name__)


def _extract_valid_delay(action: dict[str, Any], rule_id: int) -> int:
    """Return a positive int delay if ``delay_seconds`` is valid; 0 otherwise.

    Bools are rejected (Python treats ``True`` as ``1``). Invalid values are
    coerced to 0 with a warning so the action runs immediately rather than
    silently being dropped.
    """
    if "delay_seconds" not in action:
        return 0
    raw = action.get("delay_seconds")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        logger.warning(
            "rule %s action has invalid delay_seconds=%r; coerced to 0",
            rule_id,
            raw,
        )
        return 0
    return raw


def execute_actions(
    *,
    rule: Rule,
    actions: list[dict[str, Any]],
    now,
    actor_user=None,
    triggers: TriggerContext | None = None,
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
        triggers=triggers if triggers is not None else TriggerContext.empty(now),
    )

    for idx, action in enumerate(actions):
        if not isinstance(action, dict):
            action_results.append({"ok": False, "error": "invalid_action"})
            continue

        action_type = action.get("type")
        handler = get_handler(action_type) if isinstance(action_type, str) else None
        if handler is None:
            action_results.append({"ok": False, "type": str(action_type), "error": "unsupported_action"})
            continue

        ctx_for_idx = replace(ctx, action_index=idx)
        delay_seconds = _extract_valid_delay(action, rule.id)

        if delay_seconds > 0:
            try:
                pa = enqueue_pending_action(
                    rule=rule,
                    action_index=idx,
                    action_payload=action,
                    delay_seconds=delay_seconds,
                    ctx=ctx_for_idx,
                )
                action_results.append(
                    {
                        "ok": True,
                        "type": action_type,
                        "deferred": True,
                        "pending_action_id": pa.id,
                        "fire_at": pa.fire_at.isoformat(),
                        "delay_seconds": delay_seconds,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "rule %s action %s enqueue failed: %s",
                    rule.id,
                    action_type,
                    exc,
                    exc_info=True,
                )
                action_results.append({"ok": False, "type": action_type, "deferred": True, "error": str(exc)})
                error_messages.append(str(exc))
            continue

        result, error = handler(action, ctx_for_idx)
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
