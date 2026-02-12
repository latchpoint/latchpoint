from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


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
        logger.warning("zigbee2mqtt_set_value failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
        return {"ok": False, "type": "zigbee2mqtt_set_value", "entity_id": entity_id.strip(), "error": str(exc)}, str(exc)


register("zigbee2mqtt_set_value", execute)
