from __future__ import annotations

import logging
from typing import Any

from alarm.models import AlarmState
from alarm.rules.action_handlers import ActionContext, register

logger = logging.getLogger(__name__)


ALLOWED_STATES = frozenset(
    {
        AlarmState.DISARMED,
        AlarmState.PENDING,
        AlarmState.TRIGGERED,
        AlarmState.ARMED_HOME,
        AlarmState.ARMED_AWAY,
        AlarmState.ARMED_NIGHT,
        AlarmState.ARMED_VACATION,
    }
)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    """Set the alarm state directly (ADR-0094 composable primitive).

    PENDING does not auto-advance — combine with a delayed ``alarm_trigger``
    if you want a "PENDING for N seconds, then TRIGGERED" entry-delay flow.
    Use ``alarm_arm`` for the multi-step arming flow with exit-delay; this
    primitive bypasses it.
    """
    new_state = action.get("state")
    if not isinstance(new_state, str) or new_state not in ALLOWED_STATES:
        return (
            {"ok": False, "type": "alarm_set_state", "error": "invalid_state"},
            None,
        )

    try:
        snapshot = ctx.alarm_services.set_state(
            new_state=new_state,
            user=ctx.actor_user,
            reason=f"rule:{ctx.rule.id}:set_state:{new_state}",
        )
        return (
            {
                "ok": True,
                "type": "alarm_set_state",
                "state": new_state,
                "state_after": snapshot.current_state,
            },
            None,
        )
    except Exception as exc:
        logger.warning(
            "alarm_set_state failed for rule %s state=%s: %s",
            ctx.rule.id,
            new_state,
            exc,
            exc_info=True,
        )
        return (
            {"ok": False, "type": "alarm_set_state", "state": new_state, "error": str(exc)},
            str(exc),
        )


register("alarm_set_state", execute)
