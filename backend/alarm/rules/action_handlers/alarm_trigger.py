from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    """Force the alarm into TRIGGERED.

    Per ADR-0094, ``alarm_trigger`` has no embedded delay; to express an
    entry-delay flow compose with ``alarm_set_state(pending)`` plus a
    delayed ``alarm_trigger``. The executor handles ``delay_seconds``
    generically.
    """
    try:
        ctx.alarm_services.trigger(user=ctx.actor_user, reason=f"rule:{ctx.rule.id}")
        return {"ok": True, "type": "alarm_trigger"}, None
    except Exception as exc:
        logger.warning("alarm_trigger failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
        return {"ok": False, "type": "alarm_trigger", "error": str(exc)}, str(exc)


register("alarm_trigger", execute)
