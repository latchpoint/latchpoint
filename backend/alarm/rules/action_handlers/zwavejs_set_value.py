from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from alarm.state_machine.settings import get_active_settings_profile, get_setting_json

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    node_id = action.get("node_id")
    value_id = action.get("value_id")
    value = action.get("value")
    if not isinstance(node_id, int) or not isinstance(value_id, dict):
        return {"ok": False, "type": "zwavejs_set_value", "error": "missing_node_id_or_value_id"}, None
    command_class = value_id.get("commandClass")
    endpoint = value_id.get("endpoint", 0)
    prop = value_id.get("property")
    prop_key = value_id.get("propertyKey")
    if not isinstance(command_class, int) or not isinstance(endpoint, int) or prop is None:
        return {"ok": False, "type": "zwavejs_set_value", "error": "invalid_value_id"}, None
    try:
        profile = get_active_settings_profile()
        settings_obj = get_setting_json(profile, "zwavejs_connection") or {}
        if not isinstance(settings_obj, dict):
            settings_obj = {}
        ctx.zwavejs.apply_settings(settings_obj=settings_obj)
        ctx.zwavejs.ensure_connected(timeout_seconds=float(settings_obj.get("connect_timeout_seconds") or 2))
        ctx.zwavejs.set_value(
            node_id=node_id,
            endpoint=endpoint,
            command_class=command_class,
            property=prop,
            property_key=prop_key if isinstance(prop_key, (str, int)) else None,
            value=value,
        )
        return {"ok": True, "type": "zwavejs_set_value", "node_id": node_id, "value_id": value_id}, None
    except Exception as exc:
        logger.warning("zwavejs_set_value failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
        return {"ok": False, "type": "zwavejs_set_value", "node_id": node_id, "value_id": value_id, "error": str(exc)}, str(exc)


register("zwavejs_set_value", execute)
