from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    action_str = action.get("action")
    if not isinstance(action_str, str) or "." not in action_str:
        return {"ok": False, "type": "ha_call_service", "error": "invalid_action_format"}, None
    domain, service_name = action_str.split(".", 1)
    target = action.get("target")
    data = action.get("data")
    try:
        ctx.ha.call_service(
            domain=domain,
            service=service_name,
            target=target if isinstance(target, dict) else None,
            service_data=data if isinstance(data, dict) else None,
        )
        return {"ok": True, "type": "ha_call_service", "action": action_str}, None
    except Exception as exc:
        logger.warning("ha_call_service failed for rule %s: %s", ctx.rule.id, exc)
        return {"ok": False, "type": "ha_call_service", "action": action_str, "error": str(exc)}, str(exc)


register("ha_call_service", execute)
