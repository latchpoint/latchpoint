from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

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

        with patch(
            "integrations_zwavejs.manager._import_zwavejs_client",
            return_value=_fake_imports(emitted_event=emitted_event),
        ):
            manager.apply_settings(
                settings_obj={"enabled": True, "ws_url": "ws://example.test:3000", "connect_timeout_seconds": 0.2}
            )
            manager.ensure_connected(timeout_seconds=1.0)
            self.assertTrue(got_event.wait(timeout=1.0))
            self.assertTrue(received)

        manager.apply_settings(settings_obj={"enabled": False})

    @override_settings(ALLOW_ZWAVEJS_IN_TESTS=True)
    def test_without_event_bridges_node_events_reach_no_listener_or_dispatcher(self):
        # `manage.py run_task` connects this way, so its connection doesn't run rules next to the server's (#164).
        manager = ZwavejsConnectionManager()
        got_event = threading.Event()
        manager.register_event_listener(lambda _msg: got_event.set())

        emitted_event = {"source": "node", "nodeId": 12, "args": {"commandClass": 113, "eventType": 6}}
        with (
            patch(
                "integrations_zwavejs.manager._import_zwavejs_client",
                return_value=_fake_imports(emitted_event=emitted_event),
            ),
            patch("alarm.dispatcher.notify_entities_changed") as notify,
        ):
            manager.apply_settings(
                settings_obj={"enabled": True, "ws_url": "ws://example.test:3000", "connect_timeout_seconds": 0.2},
                event_bridges=False,
            )
            manager.ensure_connected(timeout_seconds=1.0)

            self.assertFalse(got_event.wait(timeout=0.8))
            self.assertEqual(manager._attached_node_ids, set())
            notify.assert_not_called()

        manager.apply_settings(settings_obj={"enabled": False})


# What zwave-js-server-python's Node emits for a Yale keypad unlock: the server's
# "notification" event data, plus the model objects the library adds to it.
class _FakeNotificationModel:
    def __repr__(self) -> str:
        return "NotificationNotification(userCode='4321')"


def _keypad_unlock_event_data(*, parameters: dict | None = None) -> dict:
    return {
        "source": "node",
        "event": "notification",
        "nodeId": 12,
        "endpointIndex": 0,
        "ccId": 113,
        "args": {
            "type": 6,
            "label": "Access Control",
            "event": 6,
            "eventLabel": "Keypad unlock operation",
            "parameters": parameters if parameters is not None else {"userId": 3, "userCode": "4321"},
        },
        "node": object(),
        "notification": _FakeNotificationModel(),
    }


class ZwavejsManagerKeypadUnlockBridgeTests(SimpleTestCase):
    """A CC 113 keypad unlock reaches the locks listener in the shape its parser reads (issue #145)."""

    @override_settings(ALLOW_ZWAVEJS_IN_TESTS=True)
    def test_keypad_unlock_reaches_the_locks_listener_and_logs_no_pin(self):
        from locks.keypad_events import KeypadUnlock
        from locks.runtime import make_event_listener

        manager = ZwavejsConnectionManager()
        submitted: list = []
        got_unlock = threading.Event()

        class _Worker:
            def submit(self, unlock):
                submitted.append(unlock)
                got_unlock.set()
                return True

        manager.register_event_listener(make_event_listener(worker=_Worker()))

        with (
            patch(
                "integrations_zwavejs.manager._import_zwavejs_client",
                return_value=_fake_imports(emitted_event=_keypad_unlock_event_data()),
            ),
            self.assertLogs("locks.runtime", level="INFO") as locks_logs,
            self.assertLogs("integrations_zwavejs.manager", level="DEBUG") as manager_logs,
        ):
            manager.apply_settings(
                settings_obj={"enabled": True, "ws_url": "ws://example.test:3000", "connect_timeout_seconds": 0.2}
            )
            manager.ensure_connected(timeout_seconds=1.0)
            self.assertTrue(got_unlock.wait(timeout=1.0))
            manager.apply_settings(settings_obj={"enabled": False})

        self.assertEqual(submitted, [KeypadUnlock(node_id=12, slot=3, event=6)])
        keypad_lines = [line for line in locks_logs.output if "zwavejs keypad event" in line]
        self.assertEqual(len(keypad_lines), 1)
        self.assertIn("'userId': 3", keypad_lines[0])
        for line in [*locks_logs.output, *manager_logs.output]:
            self.assertNotIn("4321", line)


class ZwavejsManagerSanitizeEventTests(SimpleTestCase):
    def _sanitize(self, event_data: dict) -> dict:
        return ZwavejsConnectionManager()._sanitize_event_for_log({"event": event_data})

    def test_notification_user_code_is_redacted(self):
        out = self._sanitize(_keypad_unlock_event_data())
        self.assertEqual(out["args"]["parameters"], {"userId": 3, "userCode": "***"})
        self.assertEqual(out["notification"], "<_FakeNotificationModel>")
        self.assertNotIn("4321", repr(out))

    def test_raw_buffer_parameters_are_hidden(self):
        out = self._sanitize(_keypad_unlock_event_data(parameters={"type": "Buffer", "data": [52, 51, 50, 49]}))
        self.assertEqual(out["args"]["parameters"], "***")

    def test_parameters_without_a_pin_are_kept(self):
        out = self._sanitize(_keypad_unlock_event_data(parameters={"userId": 3}))
        self.assertEqual(out["args"]["parameters"], {"userId": 3})

    def test_entry_control_event_data_is_still_redacted(self):
        out = self._sanitize({"nodeId": 12, "ccId": 111, "args": {"eventType": 5, "eventData": "1996"}})
        self.assertEqual(out["args"]["eventData"], "***")

    def test_parameters_that_arent_a_dict_or_a_number_are_hidden(self):
        for parameters in ([52, 51, 50, 49], "4321", b"4321", ("4", "3", "2", "1")):
            with self.subTest(parameters=parameters):
                out = self._sanitize(_keypad_unlock_event_data(parameters=parameters))
                self.assertEqual(out["args"]["parameters"], "***")

    def test_number_parameters_are_kept(self):
        # `None` is replaced by the helper's default, so it goes in by hand.
        for parameters in (3, 2.5):
            with self.subTest(parameters=parameters):
                out = self._sanitize(_keypad_unlock_event_data(parameters=parameters))
                self.assertEqual(out["args"]["parameters"], parameters)
        event_data = _keypad_unlock_event_data()
        event_data["args"]["parameters"] = None
        self.assertIsNone(self._sanitize(event_data)["args"]["parameters"])


def _user_code_value_event_data(*, event: str = "value updated", prop: str = "userCode", **values) -> dict:
    """A CC 99 value event as zwave-js-server sends it after a push or a readback."""
    return {
        "source": "node",
        "event": event,
        "nodeId": 12,
        "args": {
            "commandClassName": "User Code",
            "commandClass": 99,
            "endpoint": 0,
            "property": prop,
            "propertyKey": 3,
            "propertyName": prop,
            "propertyKeyName": "3",
            **values,
        },
    }


class ZwavejsManagerSanitizeUserCodeValueTests(SimpleTestCase):
    """The DEBUG ``event_in`` line logs CC 99 value events, whose values are the slot's PIN."""

    def _sanitize(self, event_data: dict) -> dict:
        return ZwavejsConnectionManager()._sanitize_event_for_log({"event": event_data})

    def test_user_code_new_and_prev_values_are_redacted(self):
        out = self._sanitize(_user_code_value_event_data(newValue="4321", prevValue="1996"))
        self.assertEqual((out["args"]["newValue"], out["args"]["prevValue"]), ("***", "***"))
        self.assertEqual(out["args"]["propertyKey"], 3)
        self.assertNotIn("4321", repr(out))
        self.assertNotIn("1996", repr(out))

    def test_value_notification_and_value_added_are_redacted(self):
        out = self._sanitize(_user_code_value_event_data(event="value notification", value="4321"))
        self.assertEqual(out["args"]["value"], "***")
        out = self._sanitize(_user_code_value_event_data(event="value added", newValue="4321"))
        self.assertEqual(out["args"]["newValue"], "***")

    def test_admin_code_is_redacted(self):
        out = self._sanitize(_user_code_value_event_data(prop="adminCode", newValue="4321"))
        self.assertEqual(out["args"]["newValue"], "***")

    def test_other_user_code_values_and_other_command_classes_are_kept(self):
        out = self._sanitize(_user_code_value_event_data(prop="userIdStatus", newValue=1, prevValue=0))
        self.assertEqual((out["args"]["newValue"], out["args"]["prevValue"]), (1, 0))
        battery = _user_code_value_event_data(newValue=80, prevValue=81)
        battery["args"]["commandClass"] = 128
        out = self._sanitize(battery)
        self.assertEqual((out["args"]["newValue"], out["args"]["prevValue"]), (80, 81))

    @override_settings(ALLOW_ZWAVEJS_IN_TESTS=True)
    def test_the_debug_event_in_line_has_no_pin_for_a_user_code_value_event(self):
        manager = ZwavejsConnectionManager()
        got_event = threading.Event()
        manager.register_event_listener(lambda _msg: got_event.set())
        emitted = _user_code_value_event_data(newValue="4321", prevValue="1996")
        with (
            patch(
                "integrations_zwavejs.manager._import_zwavejs_client",
                return_value=_fake_imports(emitted_event=emitted),
            ),
            patch("alarm.dispatcher.notify_entities_changed"),
            self.assertLogs("integrations_zwavejs.manager", level="DEBUG") as logs,
        ):
            manager.apply_settings(
                settings_obj={"enabled": True, "ws_url": "ws://example.test:3000", "connect_timeout_seconds": 0.2}
            )
            manager.ensure_connected(timeout_seconds=1.0)
            self.assertTrue(got_event.wait(timeout=1.0))
            manager.apply_settings(settings_obj={"enabled": False})

        event_in = [line for line in logs.output if "event_in" in line]
        self.assertEqual(len(event_in), 1)
        self.assertIn("'newValue': '***'", event_in[0])
        for line in logs.output:
            self.assertNotIn("4321", line)
            self.assertNotIn("1996", line)
