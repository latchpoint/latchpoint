"""Keypad unlocks from Z-Wave JS Notification CC events (issue #145, ADR-0114).

The Z-Wave JS bridge (``integrations_zwavejs.manager``) hands every node event to
its listeners as ``{"event": event_data}``. For a Notification CC (113) event
``event_data`` is the zwave-js-server ``notification`` payload::

    {"source": "node", "event": "notification", "nodeId": 12, "endpointIndex": 0, "ccId": 113,
     "args": {"type": 6, "label": "Access Control", "event": 6,
              "eventLabel": "Keypad unlock operation", "parameters": {"userId": 3}}}

Access Control (type 6) event 6 is a keypad unlock and event 34 the newer
credential unlock. ``parameters.userId`` is the CC 99 slot the code was typed
from. Event 5 is a keypad *lock* and never counts. Pure functions, no DB or
Z-Wave I/O, so they're safe on the ``zwavejs-events`` thread (ADR-0100).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CC_NOTIFICATION = 113
ACCESS_CONTROL = 6
KEYPAD_UNLOCK = 6
CREDENTIAL_UNLOCK = 34
UNLOCK_EVENTS = frozenset({KEYPAD_UNLOCK, CREDENTIAL_UNLOCK})


@dataclass(frozen=True)
class KeypadUnlock:
    """A code typed on a lock's keypad that opened it: the lock's node, the code's slot and the notification event."""

    node_id: int
    slot: int
    event: int


def _strict_int(value: object) -> int | None:
    """``value`` when it's a real int (not a bool or a numeric string), else ``None``."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _event_payload(msg: object) -> dict[str, Any] | None:
    if not isinstance(msg, dict):
        return None
    event = msg.get("event")
    return event if isinstance(event, dict) else None


def is_notification_cc_event(msg: object) -> bool:
    """Whether ``msg`` is a Notification CC (113) ``notification`` event from the bridge."""
    event = _event_payload(msg)
    if event is None:
        return False
    if event.get("event", "notification") != "notification":
        return False
    return _strict_int(event.get("ccId")) == CC_NOTIFICATION


def parse_keypad_unlock(msg: object) -> KeypadUnlock | None:
    """The :class:`KeypadUnlock` in a bridge event, or ``None`` when it isn't one.

    It's one only for CC 113, Access Control (type 6), event 6 or 34, a node id
    and a ``parameters.userId`` that's an int of 1 or more. Everything else,
    ie the keypad lock (event 5), RF and manual operations, Entry Control
    (CC 111) and a missing, 0 or non-int ``userId``, is ``None``.
    """
    if not is_notification_cc_event(msg):
        return None
    event = _event_payload(msg) or {}
    node_id = _strict_int(event.get("nodeId"))
    args = event.get("args")
    if node_id is None or node_id <= 0 or not isinstance(args, dict):
        return None
    if _strict_int(args.get("type")) != ACCESS_CONTROL:
        return None
    notification_event = _strict_int(args.get("event"))
    if notification_event not in UNLOCK_EVENTS:
        return None
    parameters = args.get("parameters")
    if not isinstance(parameters, dict):
        return None
    slot = _strict_int(parameters.get("userId"))
    if slot is None or slot < 1:
        return None
    return KeypadUnlock(node_id=node_id, slot=slot, event=notification_event)
