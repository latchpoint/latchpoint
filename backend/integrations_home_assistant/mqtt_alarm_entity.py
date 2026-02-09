from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from accounts.use_cases import code_validation
from alarm.state_machine.events import record_code_used, record_failed_code
from alarm.state_machine.settings import get_active_settings_profile, get_setting_bool, get_setting_json
from alarm.state_machine.transitions import arm, cancel_arming, disarm, get_current_snapshot
from integrations_home_assistant import mqtt_alarm_entity_status_store as status_store
from alarm.models import AlarmState
from transports_mqtt.manager import MqttNotReachable, mqtt_connection_manager

logger = logging.getLogger(__name__)

OBJECT_ID = "latchpoint_alarm"

DISCOVERY_TOPIC = f"homeassistant/alarm_control_panel/{OBJECT_ID}/config"
STATE_TOPIC = f"{OBJECT_ID}/alarm/state"
COMMAND_TOPIC = f"{OBJECT_ID}/alarm/command"
AVAILABILITY_TOPIC = f"{OBJECT_ID}/alarm/availability"
ERROR_TOPIC = f"{OBJECT_ID}/alarm/error"

_init_lock = threading.Lock()
_initialized = False


@dataclass(frozen=True)
class HomeAssistantMqttAlarmEntitySettings:
    enabled: bool
    entity_name: str
    also_rename_in_home_assistant: bool
    ha_entity_id: str


def _get_entity_settings() -> HomeAssistantMqttAlarmEntitySettings:
    """Read entity settings from the active settings profile with defaults applied."""
    profile = get_active_settings_profile()
    raw = get_setting_json(profile, "home_assistant_alarm_entity") or {}
    if not isinstance(raw, dict):
        raw = {}
    return HomeAssistantMqttAlarmEntitySettings(
        enabled=bool(raw.get("enabled", False)),
        entity_name=str(raw.get("entity_name") or "Latchpoint"),
        also_rename_in_home_assistant=bool(raw.get("also_rename_in_home_assistant", True)),
        ha_entity_id=str(raw.get("ha_entity_id") or f"alarm_control_panel.{OBJECT_ID}"),
    )


def _mqtt_enabled() -> bool:
    """Return True if MQTT is enabled and minimally configured in the active profile."""
    profile = get_active_settings_profile()
    mqtt_conn = get_setting_json(profile, "mqtt_connection") or {}
    return bool(isinstance(mqtt_conn, dict) and mqtt_conn.get("enabled") and mqtt_conn.get("host"))


def build_discovery_payload(*, entity_name: str, code_arm_required: bool) -> dict:
    """
    Home Assistant MQTT discovery payload for `alarm_control_panel`.

    Notes:
    - We publish our app states directly (they already match HA alarm states).
    - We publish commands as JSON: {"action": "<payload>", "code": "<code>"}.
      `{{ value }}` is the selected payload (payload_arm_away, payload_disarm, etc).
    """
    command_template = json.dumps({"action": "{{ value }}", "code": "{{ code }}"})
    return {
        "name": entity_name,
        "unique_id": OBJECT_ID,
        "object_id": OBJECT_ID,
        "state_topic": STATE_TOPIC,
        "command_topic": COMMAND_TOPIC,
        "availability_topic": AVAILABILITY_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
        "command_template": command_template,
        "payload_disarm": "DISARM",
        "payload_arm_home": "ARM_HOME",
        "payload_arm_away": "ARM_AWAY",
        "payload_arm_night": "ARM_NIGHT",
        "payload_arm_vacation": "ARM_VACATION",
        # Requirement: HA users must enter an alarm code to disarm.
        "code_disarm_required": True,
        # Respect app policy for arming.
        "code_arm_required": bool(code_arm_required),
    }


def publish_discovery(*, force: bool = False) -> None:
    """
    Publish HA MQTT discovery config (retained).
    """
    entity = _get_entity_settings()
    if not entity.enabled and not force:
        return
    if not _mqtt_enabled():
        return
    profile = get_active_settings_profile()
    code_arm_required = get_setting_bool(profile, "code_arm_required")
    payload = build_discovery_payload(entity_name=entity.entity_name, code_arm_required=code_arm_required)
    try:
        mqtt_connection_manager.publish(topic=DISCOVERY_TOPIC, payload=json.dumps(payload), retain=True)
        status_store.mark_discovery_published()
        # Immediately publish availability + current state so HA does not show "unknown" after discovery.
        publish_availability(online=True)
        snapshot = get_current_snapshot(process_timers=False)
        publish_state(state=snapshot.current_state)
    except MqttNotReachable:
        logger.info("MQTT not connected; discovery publish skipped.")
    except Exception as exc:
        logger.warning("Failed to publish MQTT discovery config: %s", exc)


def publish_availability(*, online: bool) -> None:
    """Publish retained availability status for the alarm entity (best-effort)."""
    if not _mqtt_enabled():
        return
    try:
        mqtt_connection_manager.publish(
            topic=AVAILABILITY_TOPIC,
            payload="online" if online else "offline",
            retain=True,
        )
        status_store.mark_availability_published()
    except Exception:
        # Best-effort.
        return


def publish_state(*, state: str) -> None:
    """Publish retained alarm state for the alarm entity (best-effort)."""
    entity = _get_entity_settings()
    if not entity.enabled:
        return
    if not _mqtt_enabled():
        return
    try:
        mqtt_connection_manager.publish(topic=STATE_TOPIC, payload=state, retain=True)
        status_store.mark_state_published()
    except Exception:
        return


def publish_error(*, action: str, error: str) -> None:
    """Publish a non-retained error message for last command processing (best-effort)."""
    if not _mqtt_enabled():
        return
    try:
        mqtt_connection_manager.publish(
            topic=ERROR_TOPIC,
            payload=json.dumps({"action": action, "error": error}),
            retain=False,
        )
        status_store.mark_error(error=error)
    except Exception:
        return


def _handle_command_payload(*, payload: str) -> tuple[str, str | None]:
    """
    Returns (action, code).
    """
    payload = (payload or "").strip()
    if not payload:
        raise ValueError("Empty payload.")
    try:
        data = json.loads(payload)
    except Exception:
        # Fallback: accept raw action string.
        return payload.strip().upper(), None
    if not isinstance(data, dict):
        raise ValueError("Invalid command payload.")
    action = str(data.get("action") or "").strip().upper()
    code = data.get("code")
    code_str = str(code).strip() if code is not None else None
    return action, code_str


_ACTION_TO_STATE = {
    "ARM_HOME": AlarmState.ARMED_HOME,
    "ARM_AWAY": AlarmState.ARMED_AWAY,
    "ARM_NIGHT": AlarmState.ARMED_NIGHT,
    "ARM_VACATION": AlarmState.ARMED_VACATION,
    "DISARM": AlarmState.DISARMED,
}


def handle_mqtt_alarm_command(*, topic: str, payload: str) -> None:
    """Handle incoming MQTT commands for the alarm entity (arm/disarm + code validation)."""
    close_old_connections()
    entity = _get_entity_settings()
    if not entity.enabled:
        return
    if topic != COMMAND_TOPIC:
        return

    # Basic global rate limiting for MQTT code attempts to reduce brute-force risk.
    # This is intentionally coarse because MQTT commands do not have user/device/ip context.
    def _rate_limit(*, key: str, limit: int, window_seconds: int) -> bool:
        """Best-effort fixed-window rate limiter backed by Django cache."""
        cache_key = f"mqtt_rate:{key}"
        try:
            current = cache.get(cache_key)
            if current is None:
                cache.set(cache_key, 1, timeout=window_seconds)
                return True
            try:
                current_int = int(current)
            except Exception:
                current_int = 0
            if current_int >= limit:
                return False
            # Best-effort increment (atomic in Redis, safe enough in LocMem).
            try:
                cache.incr(cache_key)
            except Exception:
                cache.set(cache_key, current_int + 1, timeout=window_seconds)
            return True
        except Exception:
            # If cache is unavailable, don't hard-block.
            return True

    try:
        action, raw_code = _handle_command_payload(payload=payload)
    except Exception:
        publish_error(action="UNKNOWN", error="Invalid command payload.")
        return
    target = _ACTION_TO_STATE.get(action)
    if not target:
        logger.info("Ignoring unknown MQTT alarm action: %s", action)
        publish_error(action=action, error="Unknown action.")
        return

    now = timezone.now()

    # Disarm always requires code (per requirement).
    if action == "DISARM":
        if not _rate_limit(key="disarm", limit=10, window_seconds=60):
            publish_error(action=action, error="Too many attempts. Try again later.")
            return
        if not raw_code:
            record_failed_code(user=None, action="disarm", metadata={"source": "mqtt", "reason": "missing"})
            publish_error(action=action, error="Code required.")
            return
        try:
            result = code_validation.validate_any_active_code(raw_code=raw_code, now=now)
        except Exception:
            record_failed_code(user=None, action="disarm", metadata={"source": "mqtt"})
            publish_error(action=action, error="Invalid code.")
            return
        code_obj = result.code
        user = code_obj.user
        disarm(user=user, code=code_obj, reason="mqtt_disarm")
        record_code_used(user=user, code=code_obj, action="disarm", metadata={"source": "mqtt"})
        return

    # Arm: respect existing setting, but accept a code if provided.
    profile = get_active_settings_profile()
    code_required = get_setting_bool(profile, "code_arm_required") or raw_code is not None
    code_obj = None
    user = None
    if code_required:
        if not _rate_limit(key=f"arm:{target}", limit=10, window_seconds=60):
            publish_error(action=action, error="Too many attempts. Try again later.")
            return
        if not raw_code:
            record_failed_code(
                user=None,
                action="arm",
                metadata={"source": "mqtt", "target_state": target, "reason": "missing"},
            )
            publish_error(action=action, error="Code required.")
            return
        try:
            result = code_validation.validate_any_active_code(raw_code=raw_code, now=now)
        except Exception:
            record_failed_code(user=None, action="arm", metadata={"source": "mqtt", "target_state": target})
            publish_error(action=action, error="Invalid code.")
            return
        code_obj = result.code
        user = code_obj.user

    arm(target_state=target, user=user, code=code_obj, reason="mqtt_arm")
    if code_obj is not None and user is not None:
        record_code_used(user=user, code=code_obj, action="arm", metadata={"source": "mqtt", "target_state": target})


def initialize_home_assistant_mqtt_alarm_entity_integration() -> None:
    """
    Register subscriptions and on-connect hooks.

    Safe to call multiple times.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    def _after_connect():
        """On-connect hook: publish discovery, availability, and current state."""
        close_old_connections()
        publish_availability(online=True)
        publish_discovery()
        # Publish current state on connect so HA catches up after restarts.
        snapshot = get_current_snapshot(process_timers=False)
        publish_state(state=snapshot.current_state)

    mqtt_connection_manager.subscribe(topic=COMMAND_TOPIC, qos=0, callback=handle_mqtt_alarm_command)
    mqtt_connection_manager.register_on_connect(_after_connect)


def register_integration(registry) -> None:
    """
    Register this integration with the shared integration registry.

    `registry` is intentionally duck-typed to avoid import cycles.
    """
    initialize_home_assistant_mqtt_alarm_entity_integration()
    registry.register_alarm_state_change_committed_handler(lambda state_to: publish_state(state=state_to))
