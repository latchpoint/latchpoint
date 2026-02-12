from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    try:
        ctx.alarm_services.disarm(user=ctx.actor_user, reason=f"rule:{ctx.rule.id}")
        return {"ok": True, "type": "alarm_disarm"}, None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("alarm_disarm failed for rule %s: %s", ctx.rule.id, exc)
        return {"ok": False, "type": "alarm_disarm", "error": str(exc)}, str(exc)


register("alarm_disarm", execute)
