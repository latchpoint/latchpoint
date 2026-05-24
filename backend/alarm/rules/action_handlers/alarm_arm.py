from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from alarm.rules.action_schemas import ACTION_MAX_DELAY_SECONDS

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    mode = action.get("mode")
    if not isinstance(mode, str):
        return {"ok": False, "type": "alarm_arm", "error": "missing_mode"}, None

    arming_time_seconds = action.get("arming_time_seconds")
    if arming_time_seconds is not None and (
        isinstance(arming_time_seconds, bool)
        or not isinstance(arming_time_seconds, int)
        or arming_time_seconds < 0
        or arming_time_seconds > ACTION_MAX_DELAY_SECONDS
    ):
        return {"ok": False, "type": "alarm_arm", "mode": mode, "error": "invalid_arming_time_seconds"}, None

    try:
        ctx.alarm_services.arm(
            target_state=mode,
            arming_time_seconds=arming_time_seconds,
            user=ctx.actor_user,
            reason=f"rule:{ctx.rule.id}",
        )
        result: dict[str, Any] = {"ok": True, "type": "alarm_arm", "mode": mode}
        if arming_time_seconds is not None:
            result["arming_time_seconds"] = arming_time_seconds
        return result, None
    except Exception as exc:
        logger.warning("alarm_arm failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
        return {"ok": False, "type": "alarm_arm", "mode": mode, "error": str(exc)}, str(exc)


register("alarm_arm", execute)
