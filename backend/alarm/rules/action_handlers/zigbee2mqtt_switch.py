from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    entity_id = action.get("entity_id")
    state = action.get("state")
    if not isinstance(entity_id, str) or not entity_id.strip():
        return {"ok": False, "type": "zigbee2mqtt_switch", "error": "missing_entity_id"}, None
    if state not in ("on", "off"):
        return {"ok": False, "type": "zigbee2mqtt_switch", "entity_id": entity_id.strip(), "error": "invalid_state"}, None
    try:
        ctx.zigbee2mqtt.set_entity_value(entity_id=entity_id.strip(), value={"state": state == "on"})
        return {"ok": True, "type": "zigbee2mqtt_switch", "entity_id": entity_id.strip(), "state": state}, None
    except Exception as exc:
        logger.warning("zigbee2mqtt_switch failed for rule %s: %s", ctx.rule.id, exc)
        return {
            "ok": False, "type": "zigbee2mqtt_switch", "entity_id": entity_id.strip(), "state": state, "error": str(exc)
        }, str(exc)


register("zigbee2mqtt_switch", execute)
