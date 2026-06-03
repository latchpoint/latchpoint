from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from alarm.state_machine.settings import get_active_settings_profile
from alarm.state_machine.timing import base_timing

logger = logging.getLogger(__name__)


def _resolve_delay_seconds(action: dict[str, Any], ctx: ActionContext) -> int:
    """Resolve the entry-delay grace window (seconds) for an alarm_trigger action.

    Precedence:
      * an explicit ``delay_seconds`` on the action wins — any non-negative int, where
        ``0`` means "trigger immediately"; invalid values are coerced to 0;
      * when the action omits ``delay_seconds``, fall back to the profile's global
        ``delay_time`` (entry-delay) setting, so the global setting actually governs
        rule-based triggers instead of being silently ignored.
    """
    if "delay_seconds" in action:
        raw_delay = action.get("delay_seconds")
        if isinstance(raw_delay, bool) or not isinstance(raw_delay, int) or raw_delay < 0:
            logger.warning(
                "alarm_trigger rule %s has invalid delay_seconds=%r; coerced to 0",
                ctx.rule.id,
                raw_delay,
            )
            return 0
        return raw_delay

    try:
        return max(0, int(base_timing(get_active_settings_profile()).delay_time))
    except Exception:
        logger.warning(
            "alarm_trigger rule %s could not resolve global delay_time; triggering immediately",
            ctx.rule.id,
            exc_info=True,
        )
        return 0


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    delay_seconds = _resolve_delay_seconds(action, ctx)

    if delay_seconds > 0:
        try:
            snapshot = ctx.alarm_services.trigger_with_delay(
                delay_seconds=delay_seconds,
                user=ctx.actor_user,
                reason=f"rule:{ctx.rule.id}:delay={delay_seconds}s",
            )
            return (
                {
                    "ok": True,
                    "type": "alarm_trigger",
                    "deferred": True,
                    "delay_seconds": delay_seconds,
                    "state_after": snapshot.current_state,
                },
                None,
            )
        except Exception as exc:
            logger.warning(
                "alarm_trigger trigger_with_delay failed for rule %s: %s",
                ctx.rule.id,
                exc,
                exc_info=True,
            )
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
