from __future__ import annotations

from dataclasses import dataclass

from django.core.cache import cache

from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway
from alarm.models import AlarmEvent, AlarmSettingsEntry, AlarmSettingsProfile


ha_gateway: HomeAssistantGateway = default_home_assistant_gateway


@dataclass(frozen=True)
class _NotifyConfig:
    enabled: bool
    services: tuple[str, ...]
    cooldown_seconds: int
    states: set[str]


def _parse_notify_config(raw: object) -> _NotifyConfig:
    """Parse and normalize notify settings into a typed config."""
    if not isinstance(raw, dict):
        return _NotifyConfig(enabled=False, services=("notify.notify",), cooldown_seconds=0, states=set())
    enabled = bool(raw.get("enabled", False))
    services_raw = raw.get("services", None)
    services: list[str] = []
    if isinstance(services_raw, list):
        for item in services_raw:
            if isinstance(item, str) and item.strip():
                services.append(item.strip())
    if not services:
        single = raw.get("service") if isinstance(raw.get("service"), str) else "notify.notify"
        services = [single.strip() or "notify.notify"]
    cooldown_seconds_raw = raw.get("cooldown_seconds", 0)
    try:
        cooldown_seconds = max(0, int(cooldown_seconds_raw))
    except (TypeError, ValueError):
        cooldown_seconds = 0
    states_raw = raw.get("states", [])
    normalized: set[str] = set()
    if isinstance(states_raw, list):
        for item in states_raw:
            if isinstance(item, str) and item:
                normalized.add(item)
    return _NotifyConfig(
        enabled=enabled,
        services=tuple(services),
        cooldown_seconds=cooldown_seconds,
        states=normalized,
    )


def _split_service(service: str) -> tuple[str, str] | None:
    """Split a `domain.service` string into (domain, service), returning None when invalid."""
    if not service or "." not in service:
        return None
    domain, service_name = service.split(".", 1)
    domain = domain.strip()
    service_name = service_name.strip()
    if not domain or not service_name:
        return None
    return domain, service_name


def _format_title_and_message(*, state_from: str | None, state_to: str, user_display: str | None) -> tuple[str, str]:
    """Format a notification title and message for an alarm state transition."""
    prefix = "Alarm"
    if state_to == "triggered":
        title = "ALARM TRIGGERED"
        message = "Alarm triggered."
    elif state_to == "pending":
        title = "Entry delay started"
        message = "Entry delay started."
    elif state_to == "arming":
        title = "Exit delay started"
        message = "Exit delay started."
    elif state_to == "disarmed":
        title = "Alarm disarmed"
        message = "Alarm disarmed."
    elif state_to.startswith("armed_"):
        mode = state_to.replace("armed_", "").replace("_", " ").title()
        title = f"Alarm armed ({mode})"
        message = f"Alarm armed ({mode})."
    else:
        title = f"{prefix} state changed"
        message = f"Alarm state changed to {state_to}."

    if user_display:
        message = f"{message} By {user_display}."
    if state_from:
        message = f"{message} ({state_from} → {state_to})"
    return title, message


def _resolve_actor_display(*, event_id: int) -> str | None:
    """
    Prefer the matching alarm code label (when present) so notifications can reflect which code was used.
    """

    event = (
        AlarmEvent.objects.filter(id=event_id)
        .select_related("code")
        .only(
            "id",
            "code__label",
        )
        .first()
    )
    if event:
        code = getattr(event, "code", None)
        label = (getattr(code, "label", None) or "").strip() if code else ""
        if label:
            return label

    return None


def send_state_change_notification(
    *,
    ha_gateway: HomeAssistantGateway = default_home_assistant_gateway,
    event_id: int,
    settings_profile_id: int,
    state_from: str | None,
    state_to: str,
    occurred_at_iso: str,
    user_id: str | None = None,
    ) -> dict[str, object]:
    """Send Home Assistant notify service call(s) for an alarm state transition (best-effort)."""
    try:
        profile = AlarmSettingsProfile.objects.get(id=settings_profile_id)
    except AlarmSettingsProfile.DoesNotExist:
        return {"ok": False, "skipped": True, "reason": "missing_settings_profile", "event_id": event_id}

    # `home_assistant_notify` is a deprecated setting, but we still support it for compatibility.
    entry_value = (
        AlarmSettingsEntry.objects.filter(profile=profile, key="home_assistant_notify")
        .values_list("value", flat=True)
        .first()
    )
    raw_config = entry_value if entry_value is not None else {}

    cfg = _parse_notify_config(raw_config)
    if not cfg.enabled:
        return {"ok": True, "skipped": True, "reason": "disabled", "event_id": event_id}

    if state_to not in cfg.states:
        return {
            "ok": True,
            "skipped": True,
            "reason": "state_not_selected",
            "event_id": event_id,
            "state_to": state_to,
        }

    if cfg.cooldown_seconds > 0:
        cooldown_key = f"ha_notify:{settings_profile_id}:{state_to}"
        if not cache.add(cooldown_key, "1", timeout=cfg.cooldown_seconds):
            return {"ok": True, "skipped": True, "reason": "cooldown", "event_id": event_id, "state_to": state_to}

    # Never include usernames/emails in notifications; only include a code label when available.
    user_display = _resolve_actor_display(event_id=event_id)

    title, message = _format_title_and_message(state_from=state_from, state_to=state_to, user_display=user_display)

    try:
        called: list[dict[str, str]] = []
        for full_service in cfg.services:
            domain, service = _split_service(full_service) or ("notify", "notify")
            ha_gateway.call_service(
                domain=domain,
                service=service,
                service_data={
                    "title": title,
                    "message": message,
                    "data": {
                        "event_id": event_id,
                        "occurred_at": occurred_at_iso,
                        "state_from": state_from,
                        "state_to": state_to,
                    },
                },
            )
            called.append({"domain": domain, "service": service})
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "reason": "call_failed",
            "event_id": event_id,
            "error": str(exc),
        }

    return {"ok": True, "skipped": False, "event_id": event_id, "state_to": state_to, "called": called}


def send_home_assistant_state_change_notification(
    *,
    event_id: int,
    settings_profile_id: int,
    state_from: str | None,
    state_to: str,
    occurred_at_iso: str,
    user_id: str | None = None,
) -> dict[str, object]:
    """Compatibility wrapper using the module-level default gateway."""
    return send_state_change_notification(
        ha_gateway=ha_gateway,
        event_id=event_id,
        settings_profile_id=settings_profile_id,
        state_from=state_from,
        state_to=state_to,
        occurred_at_iso=occurred_at_iso,
        user_id=user_id,
    )
