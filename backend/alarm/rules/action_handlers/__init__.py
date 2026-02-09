"""
Action handler registry for rules engine THEN actions.

Each handler module self-registers at import time via ``register()``.
The public API is ``get_handler(action_type)`` which returns the callable
or *None* for unknown types.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from alarm.gateways.home_assistant import HomeAssistantGateway
from alarm.gateways.zigbee2mqtt import Zigbee2mqttGateway
from alarm.gateways.zwavejs import ZwavejsGateway
from alarm.models import Rule


class AlarmServices(Protocol):
    def get_current_snapshot(self, *, process_timers: bool):
        """Return the current alarm snapshot, optionally processing timers."""

        ...

    def disarm(self, *, user=None, code=None, reason: str = ""):
        """Disarm the alarm."""

        ...

    def arm(self, *, target_state: str, user=None, code=None, reason: str = ""):
        """Arm the alarm to the target state."""

        ...

    def trigger(self, *, user=None, reason: str = ""):
        """Force the alarm into triggered state."""

        ...


@dataclass(frozen=True)
class ActionContext:
    """Immutable bundle of dependencies available to every action handler."""

    rule: Rule
    actor_user: Any
    alarm_services: AlarmServices
    ha: HomeAssistantGateway
    zwavejs: ZwavejsGateway
    zigbee2mqtt: Zigbee2mqttGateway


ActionHandler = Callable[[dict[str, Any], ActionContext], tuple[dict[str, Any], str | None]]

_HANDLERS: dict[str, ActionHandler] = {}


def register(action_type: str, handler: ActionHandler) -> None:
    """Register a handler for *action_type*.  Called at module-import time."""
    if action_type in _HANDLERS:
        raise ValueError(f"Duplicate handler registration for {action_type!r}")
    _HANDLERS[action_type] = handler


def get_handler(action_type: str) -> ActionHandler | None:
    """Return the handler for *action_type*, or ``None`` if not registered."""
    return _HANDLERS.get(action_type)


# Import handler modules so they self-register.
from alarm.rules.action_handlers import (  # noqa: E402, F401
    alarm_arm,
    alarm_disarm,
    alarm_trigger,
    ha_call_service,
    send_notification,
    zigbee2mqtt_light,
    zigbee2mqtt_set_value,
    zigbee2mqtt_switch,
    zwavejs_set_value,
)
