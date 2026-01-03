from __future__ import annotations

import logging
import threading
from typing import Any


logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False


def initialize() -> None:
    """Initialize control panel runtime event listeners (idempotent)."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        _initialized = True

    try:
        from alarm.gateways.zwavejs import default_zwavejs_gateway
    except Exception:
        logger.debug("Z-Wave JS gateway not available; control panels runtime not initialized.")
        return

    try:
        # `DefaultZwavejsGateway` wraps the manager; we register directly on the manager.
        manager = getattr(default_zwavejs_gateway, "manager", None)
        if manager is None:
            return
        register = getattr(manager, "register_event_listener", None)
        if not callable(register):
            return
    except Exception:
        return

    def _on_event(msg: dict[str, Any]) -> None:
        """Handle a zwave-js event and dispatch to relevant control panel handlers."""
        try:
            from control_panels.zwave_ring_keypad_v2 import handle_zwavejs_ring_keypad_v2_event

            handle_zwavejs_ring_keypad_v2_event(msg)
        except Exception:
            logger.exception("Control panels: failed handling zwavejs event")
            return

    register(_on_event)
    logger.info("Control panels: registered Z-Wave JS event listener.")

    try:
        from alarm.signals import alarm_state_change_committed
        from control_panels.zwave_ring_keypad_v2 import sync_ring_keypad_v2_devices_state
    except Exception:
        return

    def _on_alarm_state_change(sender, *, state_to: str, **_kwargs) -> None:
        """Sync keypad indicators after a committed alarm state change."""
        try:
            sync_ring_keypad_v2_devices_state()
        except Exception:
            return

    alarm_state_change_committed.connect(_on_alarm_state_change, dispatch_uid="control_panels_alarm_state_changed")
    logger.info("Control panels: registered alarm_state_change_committed handler.")
