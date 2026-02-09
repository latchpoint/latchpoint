from __future__ import annotations

from typing import Any

from alarm.rules.action_handlers import ActionContext, register


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    entity_id = action.get("entity_id")
    if not isinstance(entity_id, str) or not entity_id.strip():
        return {"ok": False, "type": "zigbee2mqtt_set_value", "error": "missing_entity_id"}, None
    if "value" not in action:
        return {"ok": False, "type": "zigbee2mqtt_set_value", "entity_id": entity_id, "error": "missing_value"}, None
    try:
        ctx.zigbee2mqtt.set_entity_value(entity_id=entity_id.strip(), value=action.get("value"))
        return {"ok": True, "type": "zigbee2mqtt_set_value", "entity_id": entity_id.strip()}, None
    except Exception as exc:
        return {"ok": False, "type": "zigbee2mqtt_set_value", "entity_id": entity_id.strip(), "error": str(exc)}, str(exc)


register("zigbee2mqtt_set_value", execute)
