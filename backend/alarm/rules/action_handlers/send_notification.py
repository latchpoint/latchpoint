from __future__ import annotations

import logging
from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from alarm.rules.pending_actions import enqueue_pending_action
from alarm.rules.template_render import render as render_template
from alarm.state_machine.settings import get_active_settings_profile
from notifications.dispatcher import get_dispatcher as get_notification_dispatcher

logger = logging.getLogger(__name__)


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    provider_id = action.get("provider_id")
    raw_message = action.get("message")
    raw_title = action.get("title")
    data = action.get("data")

    if not isinstance(provider_id, str) or not provider_id:
        return {"ok": False, "type": "send_notification", "error": "missing_provider_id"}, None
    if not isinstance(raw_message, str) or not raw_message:
        return {"ok": False, "type": "send_notification", "error": "missing_message"}, None

    raw_delay = action.get("delay_seconds", 0)
    if isinstance(raw_delay, bool) or not isinstance(raw_delay, int) or raw_delay < 0:
        if "delay_seconds" in action:
            logger.warning(
                "send_notification rule %s has invalid delay_seconds=%r; coerced to 0",
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
                    "type": "send_notification",
                    "provider_id": provider_id,
                    "deferred": True,
                    "pending_action_id": pa.id,
                    "fire_at": pa.fire_at.isoformat(),
                    "delay_seconds": delay_seconds,
                },
                None,
            )
        except Exception as exc:
            logger.warning("send_notification enqueue failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
            return (
                {"ok": False, "type": "send_notification", "deferred": True, "error": str(exc)},
                str(exc),
            )

    # ADR-0088: interpolate {{trigger.*}}, {{rule.*}}, {{now}} placeholders.
    message = render_template(raw_message, rule=ctx.rule, triggers=ctx.triggers)
    title = render_template(raw_title, rule=ctx.rule, triggers=ctx.triggers) if isinstance(raw_title, str) else None

    try:
        dispatcher = get_notification_dispatcher()
        profile = get_active_settings_profile()
        delivery, enqueue_result = dispatcher.enqueue(
            profile=profile,
            provider_id=provider_id,
            message=message,
            title=title if isinstance(title, str) and title else None,
            data=data if isinstance(data, dict) else None,
            rule_name=ctx.rule.name,
        )
        if delivery:
            return {
                "ok": True,
                "type": "send_notification",
                "provider_id": provider_id,
                "delivery_id": str(delivery.id),
                "queued": True,
            }, None
        else:
            return {
                "ok": False,
                "type": "send_notification",
                "provider_id": provider_id,
                "error": enqueue_result.message,
                "error_code": enqueue_result.error_code,
            }, enqueue_result.message
    except Exception as exc:
        logger.warning("send_notification failed for rule %s: %s", ctx.rule.id, exc, exc_info=True)
        return {
            "ok": False,
            "type": "send_notification",
            "provider_id": provider_id,
            "error": str(exc),
        }, str(exc)


register("send_notification", execute)
