from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import override_settings

from integrations_zwavejs.manager import ZwavejsConnectionManager


class _FakeAiohttp:
    class ClientSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False


def _fake_imports(*, emitted_event: dict):
    class _FakeVersion:
        home_id = 4170970308

    class _FakeNode:
        def __init__(self, *, node_id: int):
            self.node_id = node_id
            self._listeners: dict[str, list] = {}
            self.notification_listener_attached = asyncio.Event()

        def on(self, name: str, handler) -> None:
            self._listeners.setdefault(name, []).append(handler)
            if name == "notification":
                self.notification_listener_attached.set()

        def emit(self, name: str, data: dict) -> None:
            for handler in list(self._listeners.get(name, [])):
                handler(data)

    class _FakeController:
        def __init__(self, *, node: _FakeNode):
            self.nodes = {node.node_id: node}

        def on(self, _name: str, _handler) -> None:
            return

    class _FakeDriver:
        def __init__(self, *, controller: _FakeController):
            self.controller = controller

    class _FakeClient:
        def __init__(self, ws_url: str, _session):
            self.ws_server_url = ws_url
            self._closed = asyncio.Event()
            self.version = _FakeVersion()
            self.node = _FakeNode(node_id=12)
            self.driver = _FakeDriver(controller=_FakeController(node=self.node))

        async def connect(self) -> None:
            return

        async def listen(self, ready_event: asyncio.Event) -> None:
            ready_event.set()
            # Wait until the connection manager attaches node listeners, then emit a node notification.
            await asyncio.wait_for(self.node.notification_listener_attached.wait(), timeout=0.5)
            self.node.emit("notification", emitted_event)
            await self._closed.wait()

        async def disconnect(self) -> None:
            self._closed.set()

    def _noop_value_id_str(_node, _value_id):
        return "value-id"

    return _FakeAiohttp, _FakeClient, _noop_value_id_str


class ZwavejsManagerEventListenerTests(SimpleTestCase):
    @override_settings(ALLOW_ZWAVEJS_IN_TESTS=True)
    def test_register_event_listener_dispatches_emitted_events(self):
        manager = ZwavejsConnectionManager()

        received: list[dict] = []
        got_event = threading.Event()

        def _listener(msg: dict) -> None:
            received.append(msg)
            got_event.set()

        manager.register_event_listener(_listener)

        emitted_event = {
            "source": "node",
            "nodeId": 12,
            "args": {"commandClass": 111, "eventType": 5, "eventData": "1996"},
        }

        with patch("integrations_zwavejs.manager._import_zwavejs_client", return_value=_fake_imports(emitted_event=emitted_event)):
            manager.apply_settings(settings_obj={"enabled": True, "ws_url": "ws://example.test:3000", "connect_timeout_seconds": 0.2})
            manager.ensure_connected(timeout_seconds=1.0)
            self.assertTrue(got_event.wait(timeout=1.0))
            self.assertTrue(received)

        manager.apply_settings(settings_obj={"enabled": False})
