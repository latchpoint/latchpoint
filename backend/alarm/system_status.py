from __future__ import annotations

import itertools
import logging
import threading
from dataclasses import dataclass
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.dispatch import receiver
from django.utils import timezone

from alarm.signals import (
    integration_status_changed,
    integration_status_observed,
    settings_profile_changed,
)
from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
from integrations_frigate.config import normalize_frigate_settings
from integrations_frigate.runtime import get_availability_state as frigate_availability_state
from integrations_frigate.runtime import get_last_error as frigate_last_error
from integrations_frigate.runtime import get_last_ingest_at as frigate_last_ingest_at
from integrations_frigate.runtime import get_rules_run_stats as frigate_rules_run_stats
from integrations_home_assistant.config import normalize_home_assistant_connection
from integrations_zigbee2mqtt.config import normalize_zigbee2mqtt_settings
from integrations_zigbee2mqtt.status_store import get_last_seen_at as z2m_last_seen_at
from integrations_zigbee2mqtt.status_store import get_last_state as z2m_last_state
from integrations_zigbee2mqtt.status_store import get_last_sync as z2m_last_sync
from integrations_zwavejs.manager import zwavejs_connection_manager
from transports_mqtt.manager import mqtt_connection_manager

logger = logging.getLogger(__name__)

_sequence = itertools.count(1)

_Z2M_ALIVE_GRACE_SECONDS = 75


@dataclass(frozen=True)
class _IntegrationSettingsSnapshot:
    frigate_enabled: bool
    frigate_events_topic: str
    frigate_retention_seconds: int
    frigate_run_rules_on_event: bool
    frigate_run_rules_debounce_seconds: int
    frigate_run_rules_max_per_minute: int
    frigate_run_rules_kinds: list[str]
    zigbee2mqtt_enabled: bool
    zigbee2mqtt_base_topic: str
    zigbee2mqtt_run_rules_on_event: bool
    zigbee2mqtt_run_rules_debounce_seconds: int
    zigbee2mqtt_run_rules_max_per_minute: int
    zigbee2mqtt_run_rules_kinds: list[str]
    home_assistant_enabled: bool


_settings_lock = threading.Lock()
_settings_snapshot: _IntegrationSettingsSnapshot | None = None

_status_lock = threading.Lock()
_last_system_status_payload: dict[str, Any] | None = None
_last_home_assistant_status: dict[str, Any] | None = None

_last_integration_health: dict[str, bool] = {}


def _channel_broadcast(*, message: dict[str, Any]) -> None:
    """Broadcast a message to the `alarm` Channels group (best-effort)."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        "alarm",
        {
            "type": "broadcast",
            "message": message,
        },
    )


def _build_system_status_message(*, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap a system status payload into the standard websocket envelope."""
    return {
        "type": "system_status",
        "timestamp": timezone.now().isoformat(),
        "sequence": next(_sequence),
        "payload": payload,
    }


def _refresh_settings_snapshot_from_db() -> None:
    """
    Reads the active profile settings once and stores a small, thread-safe snapshot
    used by periodic status checks. Avoid calling this in a tight loop.
    """

    profile = get_active_settings_profile()

    frigate_settings = normalize_frigate_settings(get_setting_json(profile, "frigate") or {})
    z2m_settings = normalize_zigbee2mqtt_settings(get_setting_json(profile, "zigbee2mqtt") or {})

    # Treat "enabled" as the authoritative flag to decide whether we should run
    # reachability checks. Read from the active profile to avoid races with cache warm-up.
    try:
        ha_raw = get_setting_json(profile, "home_assistant_connection") or {}
        ha_conn = normalize_home_assistant_connection(ha_raw)
        ha_enabled = bool(ha_conn.get("enabled"))
    except Exception:
        ha_enabled = False

    snapshot = _IntegrationSettingsSnapshot(
        frigate_enabled=bool(frigate_settings.enabled),
        frigate_events_topic=str(frigate_settings.events_topic or ""),
        frigate_retention_seconds=int(frigate_settings.retention_seconds or 0),
        frigate_run_rules_on_event=bool(frigate_settings.run_rules_on_event),
        frigate_run_rules_debounce_seconds=int(frigate_settings.run_rules_debounce_seconds or 0),
        frigate_run_rules_max_per_minute=int(frigate_settings.run_rules_max_per_minute or 0),
        frigate_run_rules_kinds=list(frigate_settings.run_rules_kinds or []),
        zigbee2mqtt_enabled=bool(z2m_settings.enabled),
        zigbee2mqtt_base_topic=str(z2m_settings.base_topic or "zigbee2mqtt"),
        zigbee2mqtt_run_rules_on_event=bool(z2m_settings.run_rules_on_event),
        zigbee2mqtt_run_rules_debounce_seconds=int(z2m_settings.run_rules_debounce_seconds or 0),
        zigbee2mqtt_run_rules_max_per_minute=int(z2m_settings.run_rules_max_per_minute or 0),
        zigbee2mqtt_run_rules_kinds=list(z2m_settings.run_rules_kinds or []),
        home_assistant_enabled=ha_enabled,
    )
    with _settings_lock:
        global _settings_snapshot
        _settings_snapshot = snapshot


@receiver(settings_profile_changed)
def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **kwargs) -> None:
    """Refresh cached settings snapshot and broadcast updated status on profile changes."""
    try:
        _refresh_settings_snapshot_from_db()
    except Exception:
        logger.exception("system_status: failed to refresh settings snapshot (profile_id=%s reason=%s)", profile_id, reason)
        return
    # Best-effort: push an update immediately so UI reflects enable/disable quickly.
    try:
        recompute_and_broadcast_system_status(include_home_assistant=False)
    except Exception:
        logger.exception("system_status: failed to broadcast after settings change")


def _get_settings_snapshot() -> _IntegrationSettingsSnapshot:
    """Return the last settings snapshot, refreshing from DB if needed."""
    with _settings_lock:
        snap = _settings_snapshot
    if snap is not None:
        return snap
    _refresh_settings_snapshot_from_db()
    with _settings_lock:
        return _settings_snapshot or _IntegrationSettingsSnapshot(
            frigate_enabled=False,
            frigate_events_topic="",
            frigate_retention_seconds=0,
            frigate_run_rules_on_event=False,
            frigate_run_rules_debounce_seconds=0,
            frigate_run_rules_max_per_minute=0,
            frigate_run_rules_kinds=[],
            zigbee2mqtt_enabled=False,
            zigbee2mqtt_base_topic="zigbee2mqtt",
            zigbee2mqtt_run_rules_on_event=False,
            zigbee2mqtt_run_rules_debounce_seconds=0,
            zigbee2mqtt_run_rules_max_per_minute=0,
            zigbee2mqtt_run_rules_kinds=[],
            home_assistant_enabled=False,
        )


def _zigbee2mqtt_connected(*, enabled: bool, mqtt_connected: bool, now: timezone.datetime) -> bool:
    """Return True if Zigbee2MQTT appears connected based on last-seen timestamps and bridge state."""
    if not enabled:
        return False
    if not mqtt_connected:
        return False

    state = (z2m_last_state() or "").strip().lower()
    if state == "offline":
        return False

    last_seen = z2m_last_seen_at()
    if not last_seen:
        return False
    try:
        last_dt = timezone.datetime.fromisoformat(last_seen)
        last_dt = timezone.make_aware(last_dt) if timezone.is_naive(last_dt) else last_dt
    except Exception:
        return False
    return (now - last_dt) <= timezone.timedelta(seconds=_Z2M_ALIVE_GRACE_SECONDS)


def _frigate_available(
    *,
    enabled: bool,
    mqtt_connected: bool,
) -> bool:
    """Return True if Frigate is available based on the frigate/available MQTT topic."""
    if not enabled:
        return False
    if not mqtt_connected:
        return False
    # Consider available unless explicitly "offline"
    # (None means no message received yet - assume available)
    return frigate_availability_state() != "offline"


def _compute_system_status_payload(*, include_home_assistant: bool) -> dict[str, Any]:
    """Compute a combined integrations status payload for the UI/websocket."""
    now = timezone.now()
    mqtt = mqtt_connection_manager.get_status().as_dict()
    zwavejs = zwavejs_connection_manager.get_status().as_dict()

    snap = _get_settings_snapshot()
    mqtt_connected = bool(mqtt.get("connected"))

    z2m_connected = _zigbee2mqtt_connected(enabled=snap.zigbee2mqtt_enabled, mqtt_connected=mqtt_connected, now=now)
    zigbee2mqtt = {
        "enabled": snap.zigbee2mqtt_enabled,
        "base_topic": snap.zigbee2mqtt_base_topic,
        "connected": z2m_connected,
        "mqtt": mqtt,
        "sync": z2m_last_sync().as_dict(),
        "run_rules_on_event": snap.zigbee2mqtt_run_rules_on_event,
        "run_rules_debounce_seconds": snap.zigbee2mqtt_run_rules_debounce_seconds,
        "run_rules_max_per_minute": snap.zigbee2mqtt_run_rules_max_per_minute,
        "run_rules_kinds": snap.zigbee2mqtt_run_rules_kinds,
    }

    frigate = {
        "enabled": snap.frigate_enabled,
        "events_topic": snap.frigate_events_topic,
        "retention_seconds": snap.frigate_retention_seconds,
        "run_rules_on_event": snap.frigate_run_rules_on_event,
        "run_rules_debounce_seconds": snap.frigate_run_rules_debounce_seconds,
        "run_rules_max_per_minute": snap.frigate_run_rules_max_per_minute,
        "run_rules_kinds": snap.frigate_run_rules_kinds,
        "available": _frigate_available(
            enabled=snap.frigate_enabled,
            mqtt_connected=mqtt_connected,
        ),
        "mqtt": mqtt,
        "ingest": {"last_ingest_at": frigate_last_ingest_at(), "last_error": frigate_last_error()},
        "rules_run": frigate_rules_run_stats(),
    }

    if include_home_assistant and snap.home_assistant_enabled:
        from alarm.gateways.home_assistant import default_home_assistant_gateway

        try:
            ha_status = default_home_assistant_gateway.get_status()
            ha = ha_status.as_dict()
        except Exception as exc:
            ha = {"configured": True, "reachable": False, "error": str(exc)}
        with _status_lock:
            global _last_home_assistant_status
            _last_home_assistant_status = ha
    else:
        with _status_lock:
            ha = (
                dict(_last_home_assistant_status)
                if isinstance(_last_home_assistant_status, dict)
                else {"configured": bool(snap.home_assistant_enabled), "reachable": False}
            )

    return {
        "home_assistant": ha,
        "mqtt": mqtt,
        "zwavejs": zwavejs,
        "zigbee2mqtt": zigbee2mqtt,
        "frigate": frigate,
    }


def _extract_integration_health(*, payload: dict[str, Any], name: str) -> bool | None:
    """
    Return health for a known integration.

    Returns None when the integration is not configured/enabled, so persistence
    logic can ignore it.
    """
    if name == "mqtt":
        return bool(payload.get("mqtt", {}).get("connected"))
    if name == "zwavejs":
        return bool(payload.get("zwavejs", {}).get("connected"))
    if name == "zigbee2mqtt":
        zigbee2mqtt = payload.get("zigbee2mqtt", {})
        if not bool(zigbee2mqtt.get("enabled")):
            return None
        return bool(zigbee2mqtt.get("connected"))
    if name == "frigate":
        frigate = payload.get("frigate", {})
        if not bool(frigate.get("enabled")):
            return None
        return bool(frigate.get("available"))
    if name == "home_assistant":
        home_assistant = payload.get("home_assistant", {})
        if not bool(home_assistant.get("configured")):
            return None
        return bool(home_assistant.get("reachable"))
    return None


def recompute_and_broadcast_system_status(*, include_home_assistant: bool) -> None:
    """
    Recompute system status and broadcast to websocket listeners if payload changed.

    Always emits observation signals, even if the websocket payload is unchanged.
    """
    payload = _compute_system_status_payload(include_home_assistant=include_home_assistant)
    checked_at = timezone.now()
    integrations = ["mqtt", "zwavejs", "zigbee2mqtt", "frigate", "home_assistant"]

    observations: list[tuple[str, bool]] = []
    changes: list[tuple[str, bool, bool | None]] = []
    payload_changed = False

    with _status_lock:
        global _last_system_status_payload
        for name in integrations:
            is_healthy = _extract_integration_health(payload=payload, name=name)
            if is_healthy is None:
                continue

            observations.append((name, is_healthy))
            previous = _last_integration_health.get(name)
            if previous != is_healthy:
                changes.append((name, is_healthy, previous))
                _last_integration_health[name] = is_healthy

        if _last_system_status_payload != payload:
            _last_system_status_payload = payload
            payload_changed = True

    for name, is_healthy in observations:
        integration_status_observed.send(
            sender=None,
            integration=name,
            is_healthy=is_healthy,
            checked_at=checked_at,
        )

    for name, is_healthy, previous in changes:
        integration_status_changed.send(
            sender=None,
            integration=name,
            is_healthy=is_healthy,
            previous_healthy=previous,
        )

    if not payload_changed:
        return

    _channel_broadcast(message=_build_system_status_message(payload=payload))


def get_current_system_status_message() -> dict[str, Any]:
    """
    Returns the last computed system_status message if available, otherwise computes
    a best-effort snapshot without forcing a Home Assistant network check.
    """

    global _last_system_status_payload
    with _status_lock:
        payload = _last_system_status_payload
    if isinstance(payload, dict):
        return _build_system_status_message(payload=payload)
    payload = _compute_system_status_payload(include_home_assistant=False)
    with _status_lock:
        _last_system_status_payload = payload
    return _build_system_status_message(payload=payload)
