from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from control_panels.services import ControlPanelNotFound, trigger_panel

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    """Light a control panel's burglar indicator (ADR-0094).

    Equivalent in effect to ``control_panel_set_state(state="triggered")``,
    surfaced as a separate primitive so rule authors can pick the right
    scope at a glance.
    """
    panel_id = action.get("panel_id")
    if not isinstance(panel_id, int) or isinstance(panel_id, bool) or panel_id <= 0:
        return (
            {"ok": False, "type": "control_panel_trigger", "error": "invalid_panel_id"},
            None,
        )

    try:
        trigger_panel(panel_id=panel_id)
        return (
            {"ok": True, "type": "control_panel_trigger", "panel_id": panel_id},
            None,
        )
    except ControlPanelNotFound as exc:
        return (
            {
                "ok": False,
                "type": "control_panel_trigger",
                "panel_id": panel_id,
                "error": "panel_not_found",
            },
            str(exc),
        )
    except Exception as exc:
        logger.warning(
            "control_panel_trigger failed for rule %s panel_id=%s: %s",
            ctx.rule.id,
            panel_id,
            exc,
            exc_info=True,
        )
        return (
            {
                "ok": False,
                "type": "control_panel_trigger",
                "panel_id": panel_id,
                "error": str(exc),
            },
            str(exc),
        )


register("control_panel_trigger", execute)
