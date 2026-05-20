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
from alarm.rules.template_render import TriggerContext


class AlarmServices(Protocol):
    def get_current_snapshot(self, *, process_timers: bool):
        """Return the current alarm snapshot, optionally processing timers."""

        ...

    def disarm(self, *, user=None, code=None, reason: str = ""):
        """Disarm the alarm."""

        ...

    def arm(
        self,
        *,
        target_state: str,
        arming_time_seconds: int | None = None,
        user=None,
        code=None,
        reason: str = "",
    ):
        """Arm the alarm to the target state with an optional ARMING exit-delay (ADR-0095)."""

        ...

    def trigger(self, *, user=None, reason: str = ""):
        """Force the alarm into triggered state."""

        ...

    def set_state(
        self,
        *,
        new_state: str,
        user=None,
        reason: str = "",
        exit_at=None,
        metadata: dict | None = None,
    ):
        """Set the alarm state directly (ADR-0094)."""

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
    triggers: TriggerContext
    action_index: int = 0  # Position of this action in rule.definition.then (for PendingAction tracking)


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
    alarm_set_state,
    alarm_trigger,
    control_panel_set_state,
    control_panel_trigger,
    ha_call_service,
    send_notification,
    zigbee2mqtt_light,
    zigbee2mqtt_set_value,
    zigbee2mqtt_switch,
    zwavejs_set_value,
)
