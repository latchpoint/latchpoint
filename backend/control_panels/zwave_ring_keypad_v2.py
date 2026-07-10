from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from django.utils import timezone

from accounts.use_cases import code_validation
from alarm import rearm_guard
from alarm.models import AlarmState
from alarm.state_machine.events import record_code_used, record_failed_code
from alarm.state_machine.settings import get_active_settings_profile, get_setting_bool
from alarm.state_machine.transitions import arm, cancel_arming, disarm, get_current_snapshot
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

# Burglar-siren play duration — Indicator CC "Timeout: Seconds" (property_key 7). One byte,
# capped at 255. A disarm/arm transition re-selects a mode indicator and silences it early.
#
# ADR-0100 semantic model, hardware-verified 2026-07-10 (supersedes the ADR-0097 "0 = silent"
# and ADR-0099 "rising edge" readings):
# - Writing 0 ALWAYS sounds the siren with no auto-stop — even over an already-0 register.
#   (This is why the ADR-0099 teardown clear sounded the siren on BOTH arm tests on 7/10.)
# - Writing a non-zero value over a DIFFERENT register value sounds it for that many seconds.
# - Writing the same NON-ZERO value as the register is a device no-op (the silent 7/7 + 7/9
#   triggers, register stuck at 240).
# - Selecting a mode indicator silences the tone; the register does NOT self-reset.
# Therefore: the register is NEVER written outside TRIGGERED, and sounding the siren always
# uses reset-then-set (0, then the duration) — every step of which is verified to activate
# regardless of what the register holds.
_BURGLAR_SIREN_SECONDS = 240

# Bell cutoff for the periodic siren re-assert (ADR-0098): total time since the triggered
# transition after which `resync_ring_keypad_siren` stops re-sounding the tone. The final
# re-send still plays out its full _BURGLAR_SIREN_SECONDS, so the effective ceiling is
# roughly this value plus one tone duration.
_BURGLAR_SIREN_MAX_TOTAL_SECONDS = 900


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
    # The manager normalizes all events into {"event": {...}} — no legacy fallback needed.
    event_obj = msg.get("event")
    if not isinstance(event_obj, dict):
        return None
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

    if not node_id:
        return None
    if command_class != _CC_ENTRY_CONTROL:
        return None
    if event_type is None:
        return None

    # `eventData` is optional for some events (e.g. cancel); for disarm/arm it's typically the entered code.
    # Keep it as best-effort string extraction.
    event_data = event_data if isinstance(event_data, str) else None
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


def _indicator_set(
    *, device: ControlPanelDevice, property_id: int, property_key: int, value: object, log_failures: bool = False
) -> bool:
    """Best-effort Indicator CC write; returns True when the write was issued successfully.

    Swallows failures so one dropped indicator never breaks the rest of a sync. Pass
    ``log_failures=True`` for safety-critical writes (e.g. the burglar siren) so a failed
    Z-Wave write is logged instead of vanishing silently. The boolean result lets the
    reconciling sync record which register values actually reached the device (ADR-0100).
    """
    if not isinstance(device.external_id, dict):
        return False
    node_id = device.external_id.get("node_id")
    if not isinstance(node_id, int):
        return False
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
        return True
    except Exception:
        if log_failures:
            logger.warning(
                "Ring Keypad v2 indicator write failed device_id=%s property=%s key=%s",
                device.id,
                property_id,
                property_key,
                exc_info=True,
            )
        return False


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


def _clamped_beep_volume(device: ControlPanelDevice) -> int:
    """Return the device's beep volume clamped to the Ring Keypad v2 Indicator CC range (1-99)."""
    try:
        volume = int(getattr(device, "beep_volume", 50) or 50)
    except Exception:
        volume = 50
    return min(max(volume, 1), 99)


def _apply_ring_keypad_v2_volume(*, device: ControlPanelDevice, property_id: int, log_failures: bool = False) -> None:
    """
    Best-effort: set Indicator CC volume (property_key=9) for a given property_id.

    This is used for Ring Keypad v2 "sound-capable" indicators like
    entry/exit delay, code rejected, alarm, and test beeps.
    """

    volume = _clamped_beep_volume(device)
    _indicator_set(device=device, property_id=property_id, property_key=9, value=volume, log_failures=log_failures)


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


@dataclass(frozen=True)
class IndicatorWrite:
    """One Indicator CC write, with reconciliation metadata (ADR-0100)."""

    property_id: int
    property_key: int
    value: int
    # Record the value into the device's last_written_indicators on success. Countdown writes
    # (entry/exit delay seconds) are not tracked — the device decrements them to 0 on its own.
    track: bool = True
    log_failures: bool = False


def _mode_indicator_for_state(state: str) -> int:
    """Map an alarm state to the Ring Keypad v2 mode indicator property that represents it."""
    if state == AlarmState.DISARMED:
        return _IND_DISARMED
    if state in (AlarmState.ARMED_HOME, AlarmState.ARMED_NIGHT):
        # Ring Keypad v2 has no "night" mode; map to "armed stay" (home).
        return _IND_ARMED_STAY
    # armed_away / armed_vacation / fallback for any other armed state.
    return _IND_ARMED_AWAY


def _remaining_seconds(snapshot, now) -> int:
    """Return whole seconds until the snapshot's exit_at deadline (0 when absent/past)."""
    if not snapshot.exit_at:
        return 0
    return max(0, int((snapshot.exit_at - now).total_seconds()))


def _desired_indicator_writes(
    *, snapshot, now, device: ControlPanelDevice, tracked: dict, force_siren_edge: bool = False
) -> list[IndicatorWrite]:
    """
    Compute the Indicator CC writes needed to reconcile the keypad with the alarm snapshot.

    Pure function of (snapshot, tracked register state): performs no I/O. `tracked` is the
    device's last_written_indicators mapping — keys "property:property_key" for register values,
    "mode" for the last mode indicator selected, "state" for the last alarm state fully synced.

    Burglar-siren policy (ADR-0100, hardware-verified 2026-07-10): a write of 0 to the
    "Timeout: Seconds" register (13:7) ALWAYS sounds the siren with no auto-stop — even over an
    already-0 register — and a 0 -> non-zero write sounds it for that duration; mode-indicator
    selection silences it. Therefore:
    - The register is written ONLY while TRIGGERED (any 0-write outside triggered sounds the
      siren — the 2026-07-10 arm regression this replaces).
    - Sounding it always uses reset-then-set (0, then _BURGLAR_SIREN_SECONDS): both writes are
      verified activators, so the siren sounds regardless of what the register holds — no
      dependence on same-value/dedupe semantics.
    """
    state = snapshot.current_state
    volume = _clamped_beep_volume(device)
    writes: list[IndicatorWrite] = []

    if state == AlarmState.TRIGGERED:
        if tracked.get(f"{_IND_BURGLAR_ALARM}:9") != volume:
            writes.append(IndicatorWrite(_IND_BURGLAR_ALARM, 9, volume, log_failures=True))
        if tracked.get(f"{_IND_BURGLAR_ALARM}:6") != 0:
            writes.append(IndicatorWrite(_IND_BURGLAR_ALARM, 6, 0, log_failures=True))
        entering_triggered = tracked.get("state") != AlarmState.TRIGGERED
        if entering_triggered or force_siren_edge:
            writes.append(IndicatorWrite(_IND_BURGLAR_ALARM, 7, 0, log_failures=True))
            writes.append(IndicatorWrite(_IND_BURGLAR_ALARM, 7, _BURGLAR_SIREN_SECONDS, log_failures=True))
        return writes

    if state == AlarmState.ARMING:
        seconds = _remaining_seconds(snapshot, now)
        if seconds > 0:
            if tracked.get(f"{_IND_EXIT_DELAY}:9") != volume:
                writes.append(IndicatorWrite(_IND_EXIT_DELAY, 9, volume))
            writes.append(IndicatorWrite(_IND_EXIT_DELAY, 7, seconds, track=False))
        return writes

    if state == AlarmState.PENDING:
        seconds = _remaining_seconds(snapshot, now)
        if seconds > 0:
            if tracked.get(f"{_IND_ENTRY_DELAY}:9") != volume:
                writes.append(IndicatorWrite(_IND_ENTRY_DELAY, 9, volume))
            writes.append(IndicatorWrite(_IND_ENTRY_DELAY, 7, seconds, track=False))
        return writes

    # Mode states (disarmed / armed_*). Selecting a mode indicator also silences any sounding
    # alarm tone, so the write must happen whenever the state changed — even if the same mode
    # indicator was already selected before an intervening TRIGGERED period.
    mode_property = _mode_indicator_for_state(state)
    if tracked.get("mode") != mode_property or tracked.get("state") != state:
        writes.append(IndicatorWrite(mode_property, 1, 99))
    return writes


def _sync_device_state(*, device: ControlPanelDevice, force_siren_edge: bool = False) -> None:
    """Reconcile one keypad with the current alarm snapshot; raises when any write failed."""
    snapshot = get_current_snapshot(process_timers=False)
    now = timezone.now()
    tracked = dict(device.last_written_indicators or {})

    writes = _desired_indicator_writes(
        snapshot=snapshot, now=now, device=device, tracked=tracked, force_siren_edge=force_siren_edge
    )

    siren_commanded = any(w.property_id == _IND_BURGLAR_ALARM and w.property_key == 7 for w in writes)
    if siren_commanded:
        # The siren is the most safety-critical indicator: keep the greppable audit line and
        # log (rather than swallow) failed writes — a silent siren is otherwise undiagnosable.
        logger.info("Ring Keypad v2 burglar siren commanded device_id=%s", device.id)

    failures = 0
    for write in writes:
        ok = _indicator_set(
            device=device,
            property_id=write.property_id,
            property_key=write.property_key,
            value=write.value,
            log_failures=write.log_failures,
        )
        if not ok:
            failures += 1
            continue
        if write.track:
            tracked[f"{write.property_id}:{write.property_key}"] = write.value
        if write.property_key == 1 and write.value == 99:
            tracked["mode"] = write.property_id

    if failures == 0:
        # Only a fully-applied sync advances the tracked state; a partial one leaves the old
        # state so the next sync recomputes (and retries) the remaining writes.
        tracked["state"] = str(snapshot.current_state)

    if tracked != (device.last_written_indicators or {}):
        device.last_written_indicators = tracked
        device.save(update_fields=["last_written_indicators", "updated_at"])

    if failures:
        raise RuntimeError(f"{failures} keypad indicator write(s) failed")


def sync_ring_keypad_v2_devices_state(*, force_siren_edge: bool = False) -> int:
    """
    Reconcile alarm state -> Ring keypad indicators for all enabled Ring v2 devices.

    Returns the number of devices whose sync failed (0 = fully reconciled), so the panel-sync
    worker can decide to retry. Never raises.
    """

    _maybe_close_old_connections()
    try:
        snapshot = get_current_snapshot(process_timers=False)
        logger.info("Ring Keypad v2 sync: alarm_state=%s", snapshot.current_state)
    except Exception:
        logger.warning("Failed to get alarm snapshot for Ring Keypad sync", exc_info=True)
    devices = ControlPanelDevice.objects.filter(
        enabled=True,
        integration_type=ControlPanelIntegrationType.ZWAVEJS,
        kind=ControlPanelKind.RING_KEYPAD_V2,
    ).only("id", "external_id", "beep_volume", "last_error", "last_written_indicators")
    failed_devices = 0
    for device in devices:
        try:
            _sync_device_state(device=device, force_siren_edge=force_siren_edge)
            if device.last_error:
                device.last_error = ""
                device.save(update_fields=["last_error", "updated_at"])
        except Exception as exc:
            failed_devices += 1
            try:
                device.last_error = str(exc)
                device.save(update_fields=["last_error", "updated_at"])
            except Exception:
                logger.warning("Failed to save device error state", exc_info=True)
            continue
    return failed_devices


def play_code_rejected(*, device: ControlPanelDevice) -> None:
    """Play the "code not accepted" tone/LED on the keypad (blocking Z-Wave writes)."""
    _apply_ring_keypad_v2_volume(device=device, property_id=_IND_CODE_NOT_ACCEPTED)
    _indicator_set(device=device, property_id=_IND_CODE_NOT_ACCEPTED, property_key=1, value=1)


def _request_code_rejected(device: ControlPanelDevice) -> None:
    """Queue the "code not accepted" feedback on the panel-sync worker (non-blocking)."""
    from control_panels.sync_worker import panel_sync_worker

    panel_sync_worker.request_code_rejected(device_id=device.id)


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
            cancel_arming(user=None, code=None, reason="control_panel_cancel")
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
            record_failed_code(
                user=None,
                action="disarm",
                metadata={"source": "control_panel", "device_id": device.id, "reason": "missing"},
            )
            _request_code_rejected(device)
            logger.info("Ring Keypad v2 disarm rejected: missing code device_id=%s", device.id)
            return
        try:
            result = code_validation.validate_any_active_code(raw_code=raw_code, now=now)
        except code_validation.CodeValidationError:
            record_failed_code(user=None, action="disarm", metadata={"source": "control_panel", "device_id": device.id})
            _request_code_rejected(device)
            logger.info("Ring Keypad v2 disarm rejected: invalid code device_id=%s", device.id)
            return
        except Exception:
            logger.exception("Ring Keypad v2 disarm code validation failed unexpectedly device_id=%s", device.id)
            _request_code_rejected(device)
            return
        code_obj = result.code
        user = code_obj.user
        try:
            disarm(user=user, code=code_obj, reason="control_panel_disarm")
            record_code_used(
                user=user, code=code_obj, action="disarm", metadata={"source": "control_panel", "device_id": device.id}
            )
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

        # Re-arm guard: refuse an arm landing within the post-disarm window (e.g. an
        # accidental Arm press right after disarming). See alarm/rearm_guard.py.
        blocked, remaining = rearm_guard.recently_disarmed()
        if blocked:
            record_failed_code(
                user=None,
                action="arm",
                metadata={
                    "source": "control_panel",
                    "device_id": device.id,
                    "target_state": target_state,
                    "reason": "rearm_guard",
                },
            )
            _request_code_rejected(device)
            logger.info("Ring Keypad v2 arm rejected: re-arm guard device_id=%s remaining=%ss", device.id, remaining)
            return

        profile = get_active_settings_profile()
        code_required = get_setting_bool(profile, "code_arm_required") or raw_code is not None

        user = None
        code_obj = None
        if code_required:
            if not _rate_limit(device_id=device.id, action=f"arm:{target_state}"):
                return
            if not raw_code:
                record_failed_code(
                    user=None,
                    action="arm",
                    metadata={
                        "source": "control_panel",
                        "device_id": device.id,
                        "target_state": target_state,
                        "reason": "missing",
                    },
                )
                _request_code_rejected(device)
                return
            try:
                result = code_validation.validate_any_active_code(raw_code=raw_code, now=now)
            except code_validation.CodeValidationError:
                record_failed_code(
                    user=None,
                    action="arm",
                    metadata={"source": "control_panel", "device_id": device.id, "target_state": target_state},
                )
                _request_code_rejected(device)
                return
            except Exception:
                logger.exception(
                    "Ring Keypad v2 arm code validation failed unexpectedly device_id=%s target_state=%s",
                    device.id,
                    target_state,
                )
                _request_code_rejected(device)
                return
            code_obj = result.code
            user = code_obj.user

        try:
            arm(target_state=target_state, user=user, code=code_obj, reason="control_panel_arm")
            if code_obj is not None and user is not None:
                record_code_used(
                    user=user,
                    code=code_obj,
                    action="arm",
                    metadata={"source": "control_panel", "device_id": device.id, "target_state": target_state},
                )
            # Alarm state sync -> keypads happens via `alarm_state_change_committed`.
            logger.info(
                "Ring Keypad v2 arm ok device_id=%s target_state=%s user_id=%s",
                device.id,
                target_state,
                getattr(user, "id", None),
            )
        except Exception as exc:
            device.last_error = str(exc)
            device.save(update_fields=["last_error", "updated_at"])
            logger.info(
                "Ring Keypad v2 arm failed device_id=%s target_state=%s error=%s", device.id, target_state, str(exc)
            )
        return

    # Ignore other Entry Control events.
    logger.debug("Ignoring Ring Keypad v2 event_type=%s for %s", req.event_type, req.external_key)
