from __future__ import annotations

from typing import Any

from alarm.rules.action_handlers import ActionContext, register


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    mode = action.get("mode")
    if not isinstance(mode, str):
        return {"ok": False, "type": "alarm_arm", "error": "missing_mode"}, None
    try:
        ctx.alarm_services.arm(target_state=mode, user=ctx.actor_user, reason=f"rule:{ctx.rule.id}")
        return {"ok": True, "type": "alarm_arm", "mode": mode}, None
    except Exception as exc:
        return {"ok": False, "type": "alarm_arm", "mode": mode, "error": str(exc)}, str(exc)


register("alarm_arm", execute)
