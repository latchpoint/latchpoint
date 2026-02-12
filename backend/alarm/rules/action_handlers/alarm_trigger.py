from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    try:
        ctx.alarm_services.trigger(user=ctx.actor_user, reason=f"rule:{ctx.rule.id}")
        return {"ok": True, "type": "alarm_trigger"}, None
    except Exception as exc:
        logger.warning("alarm_trigger failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
        return {"ok": False, "type": "alarm_trigger", "error": str(exc)}, str(exc)


register("alarm_trigger", execute)
