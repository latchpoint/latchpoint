from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from alarm.rules.pending_actions import enqueue_pending_action

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    raw_delay = action.get("delay_seconds", 0)
    if isinstance(raw_delay, bool) or not isinstance(raw_delay, int) or raw_delay < 0:
        if "delay_seconds" in action:
            logger.warning(
                "alarm_trigger rule %s has invalid delay_seconds=%r; coerced to 0",
                ctx.rule.id,
                raw_delay,
            )
        delay_seconds = 0
    else:
        delay_seconds = raw_delay

    if delay_seconds > 0:
        try:
            pa = enqueue_pending_action(
                rule=ctx.rule,
                action_index=ctx.action_index,
                action_payload=action,
                delay_seconds=delay_seconds,
                ctx=ctx,
            )
            return (
                {
                    "ok": True,
                    "type": "alarm_trigger",
                    "deferred": True,
                    "pending_action_id": pa.id,
                    "fire_at": pa.fire_at.isoformat(),
                    "delay_seconds": delay_seconds,
                },
                None,
            )
        except Exception as exc:
            logger.warning("alarm_trigger enqueue failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
            return (
                {"ok": False, "type": "alarm_trigger", "deferred": True, "error": str(exc)},
                str(exc),
            )

    try:
        ctx.alarm_services.trigger(user=ctx.actor_user, reason=f"rule:{ctx.rule.id}")
        return {"ok": True, "type": "alarm_trigger"}, None
    except Exception as exc:
        logger.warning("alarm_trigger failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
        return {"ok": False, "type": "alarm_trigger", "error": str(exc)}, str(exc)


register("alarm_trigger", execute)
