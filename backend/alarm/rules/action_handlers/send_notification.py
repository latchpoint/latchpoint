from __future__ import annotations

from typing import Any

from alarm.rules.action_handlers import ActionContext, register
from alarm.state_machine.settings import get_active_settings_profile
from notifications.dispatcher import get_dispatcher as get_notification_dispatcher


def execute(action: dict[str, Any], ctx: ActionContext) -> tuple[dict[str, Any], str | None]:
    provider_id = action.get("provider_id")
    message = action.get("message")
    title = action.get("title")
    data = action.get("data")

    if not isinstance(provider_id, str) or not provider_id:
        return {"ok": False, "type": "send_notification", "error": "missing_provider_id"}, None
    if not isinstance(message, str) or not message:
        return {"ok": False, "type": "send_notification", "error": "missing_message"}, None

    try:
        dispatcher = get_notification_dispatcher()
        profile = get_active_settings_profile()
        delivery, enqueue_result = dispatcher.enqueue(
            profile=profile,
            provider_id=provider_id,
            message=message,
            title=title if isinstance(title, str) else None,
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
        return {
            "ok": False,
            "type": "send_notification",
            "provider_id": provider_id,
            "error": str(exc),
        }, str(exc)


register("send_notification", execute)
