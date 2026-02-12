from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    entity_id = action.get("entity_id")
    state = action.get("state")
    brightness = action.get("brightness")
    if not isinstance(entity_id, str) or not entity_id.strip():
        return {"ok": False, "type": "zigbee2mqtt_light", "error": "missing_entity_id"}, None
    if state not in ("on", "off"):
        return {"ok": False, "type": "zigbee2mqtt_light", "entity_id": entity_id.strip(), "error": "invalid_state"}, None
    if brightness is not None and not isinstance(brightness, int):
        return {"ok": False, "type": "zigbee2mqtt_light", "entity_id": entity_id.strip(), "error": "invalid_brightness"}, None

    payload: dict[str, Any] = {"state": state == "on"}
    if brightness is not None:
        payload["brightness"] = brightness
    try:
        ctx.zigbee2mqtt.set_entity_value(entity_id=entity_id.strip(), value=payload)
        return {
            "ok": True,
            "type": "zigbee2mqtt_light",
            "entity_id": entity_id.strip(),
            "state": state,
            **({"brightness": brightness} if brightness is not None else {}),
        }, None
    except Exception as exc:
        logger.warning("zigbee2mqtt_light failed for rule %s: %s", ctx.rule.id, exc)
        return {
            "ok": False,
            "type": "zigbee2mqtt_light",
            "entity_id": entity_id.strip(),
            "state": state,
            **({"brightness": brightness} if brightness is not None else {}),
            "error": str(exc),
        }, str(exc)


register("zigbee2mqtt_light", execute)
