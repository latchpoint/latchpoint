from __future__ import annotations

from typing import Any

from alarm.rules.action_handlers import ActionContext, register


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    try:
        ctx.alarm_services.disarm(user=ctx.actor_user, reason=f"rule:{ctx.rule.id}")
        return {"ok": True, "type": "alarm_disarm"}, None
    except Exception as exc:  # pragma: no cover - defensive
        return {"ok": False, "type": "alarm_disarm", "error": str(exc)}, str(exc)


register("alarm_disarm", execute)
