from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from accounts.use_cases import code_validation
from alarm import services
from alarm.models import AlarmState
from alarm.state_machine.settings import get_setting_bool
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind


logger = logging.getLogger(__name__)


# Entry Control Command Class
_CC_ENTRY_CONTROL = 111

# Indicator Command Class
_CC_INDICATOR = 135

# Entry Control event_type values (Ring Keypad v2)
_EVT_ENTER = 2
_EVT_DISARM = 3
_EVT_ARM_AWAY = 5
_EVT_ARM_STAY = 6
_EVT_CANCEL = 25

# Indicator properties (Ring Keypad v2)
_IND_DISARMED = 2
_IND_CODE_NOT_ACCEPTED = 9
_IND_ARMED_STAY = 10
_IND_ARMED_AWAY = 11
_IND_BURGLAR_ALARM = 13
_IND_ENTRY_DELAY = 17
_IND_EXIT_DELAY = 18
_IND_SOUND_DOUBLE_BEEP = 96


@dataclass(frozen=True)
class RingKeypadV2ActionRequest:
    node_id: int
    home_id: int
    event_type: int
    event_data: str | None

    @property
    def external_key(self) -> str:
        """Return the device key used to match a ControlPanelDevice (home_id + node_id)."""
        return f"zwavejs:{self.home_id}:{self.node_id}"


def _maybe_close_old_connections() -> None:
    """
    Close old DB connections for background-thread callbacks.

    IMPORTANT: Django `TestCase` wraps each test in a transaction; calling `close_old_connections()`
    from the main test thread can break the connection mid-transaction.
    """

    if threading.current_thread() is threading.main_thread():
        return
    try:
        from django.db import close_old_connections

        close_old_connections()
    except Exception:
        return


def _get_int(d: dict[str, Any], *keys: str) -> int | None:
    """Return the first int-like value from a dict for any of the provided keys."""
    for key in keys:
        value = d.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            try:
                return int(value.strip())
            except Exception:
                continue
    return None


def _get_str(d: dict[str, Any], *keys: str) -> str | None:
    """Return the first string-like value from a dict for any of the provided keys."""
    for key in keys:
        value = d.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return value
        # Some emitters may send digits as numbers.
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, dict):
            # Some emitters wrap the code/event data into an object.
            for nested_key in ("code", "userCode", "user_code", "text", "value"):
                nested = value.get(nested_key)
                if isinstance(nested, str):
                    return nested
                if isinstance(nested, (int, float)):
                    return str(nested)
    return None


def _extract_entry_control_notification(msg: dict[str, Any]) -> RingKeypadV2ActionRequest | None:
    """
    Best-effort extraction of an Entry Control notification from a zwave-js-server event message.
    """

    # The manager normalizes incoming zwave-js-server-python node events into `{"event": event_data_dict}`.
    # `event_data_dict` is shaped like NotificationEventModel:
    # {source:'node', event:'notification', nodeId, endpointIndex, ccId, args:{eventType,eventData,...}}
    event_obj = msg.get("event")
    if isinstance(event_obj, dict):
        node_id = _get_int(event_obj, "nodeId", "node_id")
        args = event_obj.get("args") if isinstance(event_obj.get("args"), dict) else None
        command_class = _get_int(event_obj, "ccId", "commandClass", "command_class", "command_class_id")
        # Some legacy emitters nested command class inside args.
        if command_class is None and args is not None:
            command_class = _get_int(args, "commandClass", "command_class", "command_class_id")
        if command_class != _CC_ENTRY_CONTROL:
            return None
        if args is None:
            return None
        event_type = _get_int(args, "eventType", "event_type")
        event_data = _get_str(args, "eventData", "event_data")
    else:
        # Legacy zwave-js-server (or other) envelope.
        event_obj = msg
        node_id = _get_int(event_obj, "nodeId", "node_id", "node")
        command_class = _get_int(event_obj, "commandClass", "command_class", "command_class_id")
        if command_class != _CC_ENTRY_CONTROL:
            return None
        event_type = _get_int(event_obj, "eventType", "event_type")
        event_data = _get_str(event_obj, "eventData", "event_data")

    if not node_id:
        return None
    if command_class != _CC_ENTRY_CONTROL:
        return None
    if event_type is None:
        return None

    # `eventData` is optional for some events (e.g. cancel); for disarm/arm it's typically the entered code.
    # Keep it as best-effort string extraction.
    if isinstance(event_data, str):
        event_data = event_data
    else:
        event_data = None
    # Z-Wave JS provides homeId via the version message; use the current connection home_id.
    try:
        from alarm.gateways.zwavejs import default_zwavejs_gateway

        home_id = int(default_zwavejs_gateway.get_home_id() or 0)
    except Exception:
        home_id = 0

    return RingKeypadV2ActionRequest(
        node_id=int(node_id),
        home_id=home_id,
        event_type=int(event_type),
        event_data=event_data,
    )


def _rate_limit(*, device_id: int, action: str, limit: int = 10, window_seconds: int = 60) -> bool:
    """Best-effort fixed-window rate limiter backed by Django cache."""
    from django.core.cache import cache

    cache_key = f"control_panels:ring_keypad_v2:{device_id}:{action}"
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
        try:
            cache.incr(cache_key)
        except Exception:
            cache.set(cache_key, current_int + 1, timeout=window_seconds)
        return True
    except Exception:
        return True


def _indicator_set(*, device: ControlPanelDevice, property_id: int, property_key: int, value: object) -> None:
    """Best-effort Indicator CC write; swallows all failures."""
    if not isinstance(device.external_id, dict):
        return
    node_id = device.external_id.get("node_id")
    if not isinstance(node_id, int):
        return
    try:
        from alarm.gateways.zwavejs import default_zwavejs_gateway

        default_zwavejs_gateway.set_value(
            node_id=node_id,
            endpoint=0,
            command_class=_CC_INDICATOR,
            property=property_id,
            property_key=property_key,
            value=value,
        )
    except Exception:
        return


def _indicator_set_strict(*, device: ControlPanelDevice, property_id: int, property_key: int, value: object) -> None:
    """Indicator CC write that validates configuration and node presence, raising on failure."""
    if not isinstance(device.external_id, dict):
        raise ValueError("Control panel external_id is missing.")
    node_id = device.external_id.get("node_id")
    if not isinstance(node_id, int):
        raise ValueError("Control panel external_id.node_id is required.")

    from alarm.gateways.zwavejs import default_zwavejs_gateway

    default_zwavejs_gateway.ensure_connected(timeout_seconds=5.0)
    state = default_zwavejs_gateway.controller_get_state(timeout_seconds=10)
    nodes = (state.get("state") or {}).get("nodes") if isinstance(state, dict) else None
    node_ids: set[int] = set()
    if isinstance(nodes, list):
        for n in nodes:
            if isinstance(n, dict) and isinstance(n.get("id"), int):
                node_ids.add(int(n["id"]))
            elif isinstance(n, dict) and isinstance(n.get("nodeId"), int):
                node_ids.add(int(n["nodeId"]))
    elif isinstance(nodes, dict):
        for key, val in nodes.items():
            if isinstance(key, int):
                node_ids.add(key)
            elif isinstance(key, str) and key.isdigit():
                node_ids.add(int(key))
            if isinstance(val, dict):
                if isinstance(val.get("id"), int):
                    node_ids.add(int(val["id"]))
                elif isinstance(val.get("nodeId"), int):
                    node_ids.add(int(val["nodeId"]))

    if int(node_id) not in node_ids and node_ids:
        raise ValueError(f"Node {node_id} not found in controller state.")

    default_zwavejs_gateway.set_value(
        node_id=int(node_id),
        endpoint=0,
        command_class=_CC_INDICATOR,
        property=property_id,
        property_key=property_key,
        value=value,
    )


def _apply_ring_keypad_v2_volume(*, device: ControlPanelDevice, property_id: int) -> None:
    """
    Best-effort: set Indicator CC volume (property_key=9) for a given property_id.

    This is used for Ring Keypad v2 "sound-capable" indicators like entry/exit delay, code rejected, alarm, and test beeps.
    """

    try:
        volume = int(getattr(device, "beep_volume", 50) or 50)
    except Exception:
        volume = 50

    if volume < 1:
        volume = 1
    if volume > 99:
        volume = 99

    _indicator_set(device=device, property_id=property_id, property_key=9, value=volume)


def test_ring_keypad_v2_beep(*, device: ControlPanelDevice, volume: int = 50) -> None:
    """
    Best-effort "beep" test for Ring Keypad v2.

    Uses Indicator CC sound property 96 (electronic double beep) with property_key=9 (volume).
    """

    if device.integration_type != ControlPanelIntegrationType.ZWAVEJS or device.kind != ControlPanelKind.RING_KEYPAD_V2:
        raise NotImplementedError("Test beep is not supported for this panel.")

    if volume < 1:
        volume = 1
    if volume > 99:
        volume = 99

    _indicator_set_strict(device=device, property_id=_IND_SOUND_DOUBLE_BEEP, property_key=9, value=volume)


def _sync_device_state(*, device: ControlPanelDevice) -> None:
    """Update keypad indicator state based on the current alarm snapshot (best-effort)."""
    snapshot = services.get_current_snapshot(process_timers=False)
    now = timezone.now()

    if snapshot.current_state == AlarmState.DISARMED:
        _indicator_set(device=device, property_id=_IND_DISARMED, property_key=1, value=99)
        return
    if snapshot.current_state == AlarmState.ARMED_HOME:
        _indicator_set(device=device, property_id=_IND_ARMED_STAY, property_key=1, value=99)
        return
    if snapshot.current_state == AlarmState.ARMED_NIGHT:
        # Ring Keypad v2 has no "night" mode; map to "armed stay" (home).
        _indicator_set(device=device, property_id=_IND_ARMED_STAY, property_key=1, value=99)
        return
    if snapshot.current_state in (AlarmState.ARMED_AWAY, AlarmState.ARMED_VACATION):
        _indicator_set(device=device, property_id=_IND_ARMED_AWAY, property_key=1, value=99)
        return
    if snapshot.current_state == AlarmState.ARMING:
        seconds = 0
        if snapshot.exit_at:
            seconds = max(0, int((snapshot.exit_at - now).total_seconds()))
        if seconds <= 0:
            return
        _apply_ring_keypad_v2_volume(device=device, property_id=_IND_EXIT_DELAY)
        _indicator_set(device=device, property_id=_IND_EXIT_DELAY, property_key=7, value=seconds)
        return
    if snapshot.current_state == AlarmState.PENDING:
        seconds = 0
        if snapshot.exit_at:
            seconds = max(0, int((snapshot.exit_at - now).total_seconds()))
        if seconds <= 0:
            return
        _apply_ring_keypad_v2_volume(device=device, property_id=_IND_ENTRY_DELAY)
        _indicator_set(device=device, property_id=_IND_ENTRY_DELAY, property_key=7, value=seconds)
        return
    if snapshot.current_state == AlarmState.TRIGGERED:
        # Alarm indicators are sticky until a mode is selected; keep value minimal to avoid volume/brightness quirks.
        _apply_ring_keypad_v2_volume(device=device, property_id=_IND_BURGLAR_ALARM)
        _indicator_set(device=device, property_id=_IND_BURGLAR_ALARM, property_key=1, value=1)
        return

    # Best-effort fallback for other armed states.
    _indicator_set(device=device, property_id=_IND_ARMED_AWAY, property_key=1, value=99)


def sync_ring_keypad_v2_devices_state() -> None:
    """
    Sync alarm state -> Ring keypad indicators for all enabled Ring v2 devices.
    """

    _maybe_close_old_connections()
    try:
        snapshot = services.get_current_snapshot(process_timers=False)
        logger.info("Ring Keypad v2 sync: alarm_state=%s", snapshot.current_state)
    except Exception:
        pass
    devices = ControlPanelDevice.objects.filter(
        enabled=True,
        integration_type=ControlPanelIntegrationType.ZWAVEJS,
        kind=ControlPanelKind.RING_KEYPAD_V2,
    ).only("id", "external_id", "last_error")
    for device in devices:
        try:
            _sync_device_state(device=device)
            if device.last_error:
                device.last_error = ""
                device.save(update_fields=["last_error", "updated_at"])
        except Exception as exc:
            try:
                device.last_error = str(exc)
                device.save(update_fields=["last_error", "updated_at"])
            except Exception:
                pass
            continue


def handle_zwavejs_ring_keypad_v2_event(msg: dict[str, Any]) -> None:
    """
    Handle a raw zwave-js-server event and, if it matches an enabled Ring Keypad v2 device,
    translate it into an alarm action (arm/disarm/cancel) using this app's code validation.
    """

    req = _extract_entry_control_notification(msg)
    if req is None:
        return
    if req.home_id <= 0:
        # Not yet initialized (no version/homeId received).
        return

    _maybe_close_old_connections()
    try:
        device = ControlPanelDevice.objects.get(
            enabled=True,
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            external_key=req.external_key,
        )
    except ControlPanelDevice.DoesNotExist:
        # Fallback: if home_id changed or was mis-recorded, match by node_id.
        candidates = list(
            ControlPanelDevice.objects.filter(
                enabled=True,
                integration_type=ControlPanelIntegrationType.ZWAVEJS,
                kind=ControlPanelKind.RING_KEYPAD_V2,
                external_id__node_id=req.node_id,
            )[:2]
        )
        if len(candidates) != 1:
            logger.info(
                "Ring Keypad v2 event for unknown device external_key=%s node_id=%s event_type=%s",
                req.external_key,
                req.node_id,
                req.event_type,
            )
            return
        device = candidates[0]

    now = timezone.now()
    device.last_seen_at = now
    device.last_error = ""
    device.save(update_fields=["last_seen_at", "last_error", "updated_at"])

    raw_code = (req.event_data or "").strip() or None
    if req.event_type in (_EVT_CANCEL, _EVT_DISARM, _EVT_ENTER, _EVT_ARM_AWAY, _EVT_ARM_STAY):
        logger.info(
            "Ring Keypad v2 event device_id=%s node_id=%s event_type=%s has_code=%s",
            device.id,
            req.node_id,
            req.event_type,
            bool(raw_code),
        )

    if req.event_type == _EVT_CANCEL:
        try:
            services.cancel_arming(user=None, code=None, reason="control_panel_cancel")
            # Alarm state sync -> keypads happens via `alarm_state_change_committed`.
        except Exception as exc:
            device.last_error = str(exc)
            device.save(update_fields=["last_error", "updated_at"])
            logger.info("Ring Keypad v2 cancel failed device_id=%s error=%s", device.id, str(exc))
        return

    if req.event_type in (_EVT_DISARM, _EVT_ENTER):
        if not _rate_limit(device_id=device.id, action="disarm"):
            return
        if not raw_code:
            services.record_failed_code(user=None, action="disarm", metadata={"source": "control_panel", "device_id": device.id, "reason": "missing"})
            _apply_ring_keypad_v2_volume(device=device, property_id=_IND_CODE_NOT_ACCEPTED)
            _indicator_set(device=device, property_id=_IND_CODE_NOT_ACCEPTED, property_key=1, value=1)
            logger.info("Ring Keypad v2 disarm rejected: missing code device_id=%s", device.id)
            return
        try:
            result = code_validation.validate_any_active_code(raw_code=raw_code, now=now)
        except Exception:
            services.record_failed_code(user=None, action="disarm", metadata={"source": "control_panel", "device_id": device.id})
            _apply_ring_keypad_v2_volume(device=device, property_id=_IND_CODE_NOT_ACCEPTED)
            _indicator_set(device=device, property_id=_IND_CODE_NOT_ACCEPTED, property_key=1, value=1)
            logger.info("Ring Keypad v2 disarm rejected: invalid code device_id=%s", device.id)
            return
        code_obj = result.code
        user = code_obj.user
        try:
            services.disarm(user=user, code=code_obj, reason="control_panel_disarm")
            services.record_code_used(user=user, code=code_obj, action="disarm", metadata={"source": "control_panel", "device_id": device.id})
            # Alarm state sync -> keypads happens via `alarm_state_change_committed`.
            logger.info("Ring Keypad v2 disarm ok device_id=%s user_id=%s", device.id, getattr(user, "id", None))
        except Exception as exc:
            device.last_error = str(exc)
            device.save(update_fields=["last_error", "updated_at"])
            logger.info("Ring Keypad v2 disarm failed device_id=%s error=%s", device.id, str(exc))
        return

    if req.event_type in (_EVT_ARM_AWAY, _EVT_ARM_STAY):
        # Ring v2 only provides Arm Away and Arm Stay; Arm Stay maps to armed_home.
        target_state = AlarmState.ARMED_AWAY if req.event_type == _EVT_ARM_AWAY else AlarmState.ARMED_HOME

        profile = services.get_active_settings_profile()
        code_required = get_setting_bool(profile, "code_arm_required") or raw_code is not None

        user = None
        code_obj = None
        if code_required:
            if not _rate_limit(device_id=device.id, action=f"arm:{target_state}"):
                return
            if not raw_code:
                services.record_failed_code(
                    user=None,
                    action="arm",
                    metadata={"source": "control_panel", "device_id": device.id, "target_state": target_state, "reason": "missing"},
                )
                _apply_ring_keypad_v2_volume(device=device, property_id=_IND_CODE_NOT_ACCEPTED)
                _indicator_set(device=device, property_id=_IND_CODE_NOT_ACCEPTED, property_key=1, value=1)
                return
            try:
                result = code_validation.validate_any_active_code(raw_code=raw_code, now=now)
            except Exception:
                services.record_failed_code(
                    user=None,
                    action="arm",
                    metadata={"source": "control_panel", "device_id": device.id, "target_state": target_state},
                )
                _apply_ring_keypad_v2_volume(device=device, property_id=_IND_CODE_NOT_ACCEPTED)
                _indicator_set(device=device, property_id=_IND_CODE_NOT_ACCEPTED, property_key=1, value=1)
                return
            code_obj = result.code
            user = code_obj.user

        try:
            services.arm(target_state=target_state, user=user, code=code_obj, reason="control_panel_arm")
            if code_obj is not None and user is not None:
                services.record_code_used(user=user, code=code_obj, action="arm", metadata={"source": "control_panel", "device_id": device.id, "target_state": target_state})
            # Alarm state sync -> keypads happens via `alarm_state_change_committed`.
            logger.info("Ring Keypad v2 arm ok device_id=%s target_state=%s user_id=%s", device.id, target_state, getattr(user, "id", None))
        except Exception as exc:
            device.last_error = str(exc)
            device.save(update_fields=["last_error", "updated_at"])
            logger.info("Ring Keypad v2 arm failed device_id=%s target_state=%s error=%s", device.id, target_state, str(exc))
        return

    # Ignore other Entry Control events.
    logger.debug("Ignoring Ring Keypad v2 event_type=%s for %s", req.event_type, req.external_key)
