"""`manage.py run_task` opens just the connections a task declares, and closes them after (#164)."""

from __future__ import annotations

import importlib
import sys
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from alarm.tests.settings_test_utils import EncryptionTestMixin, set_profile_settings
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from scheduler import Every, get_task, register, registry


class _FakeMqttGateway:
    def __init__(self, *, connects: bool = True) -> None:
        self.applied: list[dict] = []
        self.connected = False
        self._connects = connects

    def apply_settings(self, *, settings) -> None:
        self.applied.append(dict(settings))
        self.connected = bool(settings.get("enabled")) and self._connects

    def get_status(self):
        return SimpleNamespace(connected=self.connected, last_error=None if self.connected else "refused")


class _FakeZwavejsGateway:
    def __init__(self, *, connects: bool = True) -> None:
        self.applied: list[dict] = []
        self.event_bridges: list[bool] = []
        self.connected = False
        self._connects = connects

    def apply_settings(self, *, settings_obj, event_bridges: bool = True) -> None:
        self.applied.append(dict(settings_obj))
        self.event_bridges.append(event_bridges)
        self.connected = bool(settings_obj.get("enabled")) and self._connects

    def ensure_connected(self, *, timeout_seconds: float = 5.0) -> None:
        if not self.connected:
            raise TimeoutError("Timed out waiting for Z-Wave JS driver ready.")


def _registered(module_name: str, task_name: str):
    """Import `module_name` fresh and return how it registers `task_name`.

    Other tests clear the task registry, so this doesn't rely on it. The module is put back by hand rather than
    with `patch.dict(sys.modules)`, which clears the whole dict to restore it.
    """
    package_name, _, attr = module_name.rpartition(".")
    package = importlib.import_module(package_name)
    original = sys.modules.pop(module_name)
    try:
        with patch.dict(registry._tasks, clear=True), patch.object(package, attr):
            importlib.import_module(module_name)
            return get_task(task_name)
    finally:
        sys.modules[module_name] = original


class RunTaskConnectionsTests(EncryptionTestMixin, TestCase):
    def setUp(self):
        registry_patch = patch.dict(registry._tasks, clear=True)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)

        set_profile_settings(
            ensure_active_settings_profile(),
            mqtt={"enabled": True, "host": "127.0.0.1", "port": 1883, "connect_timeout_seconds": 1},
            zwavejs={"enabled": True, "ws_url": "ws://127.0.0.1:3000", "connect_timeout_seconds": 1},
        )
        self.mqtt = _FakeMqttGateway()
        self.zwavejs = _FakeZwavejsGateway()
        for target, fake in (
            ("alarm.gateways.mqtt.default_mqtt_gateway", self.mqtt),
            ("alarm.gateways.zwavejs.default_zwavejs_gateway", self.zwavejs),
        ):
            gateway_patch = patch(target, fake)
            gateway_patch.start()
            self.addCleanup(gateway_patch.stop)

        self.seen: dict[str, bool] = {}

    def _register(self, name: str, connections: tuple[str, ...], *, fails: bool = False) -> None:
        @register(name, schedule=Every(seconds=60), connections=connections)
        def _task():
            self.seen = {"mqtt": self.mqtt.connected, "zwavejs": self.zwavejs.connected}
            if fails:
                raise RuntimeError("boom")

    def _run(self, name: str) -> tuple[str, str]:
        out, err = StringIO(), StringIO()
        call_command("run_task", name, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_opens_only_what_the_task_declares_and_closes_it(self):
        self._register("needs_zwavejs", ("zwavejs",))

        out, _err = self._run("needs_zwavejs")

        self.assertEqual(self.seen, {"mqtt": False, "zwavejs": True})
        self.assertEqual(self.mqtt.applied, [])
        self.assertEqual([s["enabled"] for s in self.zwavejs.applied], [True, False])
        self.assertFalse(self.zwavejs.connected)
        self.assertIn("Connected to Z-Wave JS for this run.", out)

    def test_the_zwavejs_connection_doesnt_bridge_node_events(self):
        # Node events would otherwise reach a rule dispatcher in this process too, next to the server's.
        self._register("needs_zwavejs", ("zwavejs",))

        self._run("needs_zwavejs")

        self.assertEqual(self.zwavejs.event_bridges, [False, False])

    def test_opens_both_when_declared(self):
        self._register("needs_both", ("mqtt", "zwavejs"))

        self._run("needs_both")

        self.assertEqual(self.seen, {"mqtt": True, "zwavejs": True})
        self.assertFalse(self.mqtt.connected)
        self.assertFalse(self.zwavejs.connected)

    def test_opens_nothing_for_other_tasks(self):
        self._register("db_only", ())

        self._run("db_only")

        self.assertEqual(self.seen, {"mqtt": False, "zwavejs": False})
        self.assertEqual(self.mqtt.applied, [])
        self.assertEqual(self.zwavejs.applied, [])

    def test_closes_them_when_the_task_fails(self):
        self._register("fails", ("mqtt", "zwavejs"), fails=True)

        with self.assertRaises(CommandError):
            self._run("fails")

        self.assertEqual(self.seen, {"mqtt": True, "zwavejs": True})
        self.assertFalse(self.mqtt.connected)
        self.assertFalse(self.zwavejs.connected)

    def test_runs_anyway_when_a_connection_doesnt_come_up(self):
        self.mqtt._connects = False
        self.zwavejs._connects = False
        self._register("unreachable", ("mqtt", "zwavejs"))

        _out, err = self._run("unreachable")

        self.assertEqual(self.seen, {"mqtt": False, "zwavejs": False})
        self.assertIn("MQTT didn't connect within 1s (refused).", err)
        self.assertIn("Z-Wave JS didn't connect within 1s", err)
        self.assertEqual([s["enabled"] for s in self.mqtt.applied], [True, False])
        self.assertEqual([s["enabled"] for s in self.zwavejs.applied], [True, False])

    def test_skips_a_disabled_integration(self):
        set_profile_settings(ensure_active_settings_profile(), zwavejs={"enabled": False})
        self._register("needs_zwavejs", ("zwavejs",))

        out, _err = self._run("needs_zwavejs")

        self.assertEqual(self.zwavejs.applied, [])
        self.assertIn("Z-Wave JS is disabled, so the task runs without it.", out)

    def test_rejects_an_unknown_connection(self):
        with self.assertRaises(ValueError):
            register("typo", schedule=Every(seconds=60), connections=("zwave",))


class TaskConnectionDeclarationTests(TestCase):
    def test_tasks_that_talk_to_devices_declare_their_connections(self):
        for module_name, task_name, expected in (
            ("control_panels.tasks", "resync_ring_keypad_siren", ("zwavejs",)),
            ("locks.tasks", "push_pending_door_codes", ("zwavejs",)),
            ("alarm.tasks", "fire_due_pending_actions", ("mqtt", "zwavejs")),
            ("alarm.tasks", "process_due_rule_runtimes", ("mqtt", "zwavejs")),
            ("alarm.tasks", "cleanup_old_events", ()),
        ):
            with self.subTest(task=task_name):
                self.assertEqual(_registered(module_name, task_name).connections, expected)
