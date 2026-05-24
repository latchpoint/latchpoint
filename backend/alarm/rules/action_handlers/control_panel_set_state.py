from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from control_panels.services import ControlPanelNotFound, apply_panel_state, resume_auto

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    """Set a control panel into an explicit indicator state (ADR-0094).

    Flips ``follow_alarm_state=False`` on the panel so it stops mirroring
    the central alarm state. ``state="auto"`` re-enables the mirror and
    re-syncs from the current alarm snapshot.
    """
    panel_id = action.get("panel_id")
    state = action.get("state")
    countdown_seconds = action.get("countdown_seconds")

    if not isinstance(panel_id, int) or isinstance(panel_id, bool) or panel_id <= 0:
        return (
            {"ok": False, "type": "control_panel_set_state", "error": "invalid_panel_id"},
            None,
        )
    if state not in ("pending", "disarmed", "armed_stay", "armed_away", "triggered", "auto"):
        return (
            {"ok": False, "type": "control_panel_set_state", "error": "invalid_state"},
            None,
        )

    try:
        if state == "auto":
            resume_auto(panel_id=panel_id)
        else:
            apply_panel_state(
                panel_id=panel_id,
                state=state,
                countdown_seconds=(
                    countdown_seconds
                    if isinstance(countdown_seconds, int) and not isinstance(countdown_seconds, bool)
                    else None
                ),
            )
        return (
            {
                "ok": True,
                "type": "control_panel_set_state",
                "panel_id": panel_id,
                "state": state,
            },
            None,
        )
    except ControlPanelNotFound as exc:
        return (
            {
                "ok": False,
                "type": "control_panel_set_state",
                "panel_id": panel_id,
                "error": "panel_not_found",
            },
            str(exc),
        )
    except Exception as exc:
        logger.warning(
            "control_panel_set_state failed for rule %s panel_id=%s state=%s: %s",
            ctx.rule.id,
            panel_id,
            state,
            exc,
            exc_info=True,
        )
        return (
            {
                "ok": False,
                "type": "control_panel_set_state",
                "panel_id": panel_id,
                "error": str(exc),
            },
            str(exc),
        )


register("control_panel_set_state", execute)
