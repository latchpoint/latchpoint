from __future__ import annotations

import asyncio
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import override_settings

from integrations_zwavejs.manager import ZwavejsConnectionManager, ZwavejsNotReachable


class _FakeAiohttp:
    class ClientSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False


def _fake_imports(*, driver_ready: bool):
    class _FakeClient:
        def __init__(self, ws_url: str, _session):
            self.ws_server_url = ws_url
            self._closed = asyncio.Event()

        async def connect(self) -> None:
            return

        async def listen(self, ready_event: asyncio.Event) -> None:
            if driver_ready:
                ready_event.set()
            await self._closed.wait()

        async def disconnect(self) -> None:
            self._closed.set()

    def _noop_value_id_str(_node, _value_id):
        return "value-id"

    return _FakeAiohttp, _FakeClient, _noop_value_id_str


class ZwavejsTestConnectionValidationTests(SimpleTestCase):
    @override_settings(ALLOW_ZWAVEJS_IN_TESTS=True)
    def test_test_connection_rejects_non_zwave_server(self):
        manager = ZwavejsConnectionManager()
        with patch("integrations_zwavejs.manager._import_zwavejs_client", return_value=_fake_imports(driver_ready=False)):
            with self.assertRaises(ZwavejsNotReachable):
                manager.test_connection(settings_obj={"ws_url": "ws://example.test:3000"}, timeout_seconds=0.05)

    @override_settings(ALLOW_ZWAVEJS_IN_TESTS=True)
    def test_test_connection_accepts_zwave_server(self):
        manager = ZwavejsConnectionManager()
        with patch("integrations_zwavejs.manager._import_zwavejs_client", return_value=_fake_imports(driver_ready=True)):
            manager.test_connection(settings_obj={"ws_url": "ws://example.test:3000"}, timeout_seconds=0.2)
