"""`manage.py run_task` publishes an alarm state change to the HA alarm entity, and never writes the keypads (#173)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from alarm.models import AlarmState, AlarmStateSnapshot
from alarm.state_machine import transitions
from alarm.tests.settings_test_utils import EncryptionTestMixin, set_profile_settings
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from scheduler import Every, register, registry
from scheduler.tests.test_run_task_connections import _FakeMqttGateway, _FakeZwavejsGateway

_KEYPAD_WARNING = "only the server's panel sync worker writes to the keypads"


class RunTaskAlarmStateTests(EncryptionTestMixin, TestCase):
    def setUp(self):
        registry_patch = patch.dict(registry._tasks, clear=True)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)

        self.profile = ensure_active_settings_profile()
        set_profile_settings(
            self.profile,
            arming_time=0,
            mqtt={"enabled": True, "host": "127.0.0.1", "port": 1883, "connect_timeout_seconds": 1},
            zwavejs={"enabled": True, "ws_url": "ws://127.0.0.1:3000", "connect_timeout_seconds": 1},
            home_assistant_alarm_entity={"enabled": True},
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

        self.published: list[tuple[str, bool]] = []

        def _publish_state(*, state: str) -> None:
            self.published.append((state, self.mqtt.connected))

        publish_patch = patch("integrations_home_assistant.mqtt_alarm_entity.publish_state", side_effect=_publish_state)
        publish_patch.start()
        self.addCleanup(publish_patch.stop)

        # Any keypad write from this process would go through the panel sync worker or the Indicator CC writes.
        for target in (
            "control_panels.sync_worker.panel_sync_worker.request_sync",
            "control_panels.zwave_ring_keypad_v2._indicator_set",
            "control_panels.zwave_ring_keypad_v2._indicator_set_strict",
        ):
            keypad_patch = patch(target, side_effect=AssertionError("run_task wrote the keypads"))
            keypad_patch.start()
            self.addCleanup(keypad_patch.stop)

    def _register(self, name: str, *, connections: tuple[str, ...] = (), arms: bool = True, fails: bool = False):
        @register(name, schedule=Every(seconds=60), connections=connections)
        def _task():
            if arms:
                # The commit runs the `alarm_state_change_committed` receivers, like a real task's would.
                with self.captureOnCommitCallbacks(execute=True):
                    transitions.arm(target_state=AlarmState.ARMED_AWAY, reason="test")
            if fails:
                raise RuntimeError("boom")

    def _run(self, name: str) -> tuple[str, str]:
        out, err = StringIO(), StringIO()
        call_command("run_task", name, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def _add_keypad(self) -> None:
        ControlPanelDevice.objects.create(
            name="Front keypad",
            integration_type=ControlPanelIntegrationType.ZWAVEJS,
            kind=ControlPanelKind.RING_KEYPAD_V2,
            external_key="zwavejs:1:5",
            external_id={"home_id": 1, "node_id": 5},
        )

    def test_publishes_the_new_state_over_an_mqtt_connection_opened_for_it(self):
        # `process_alarm_timers` changes the state but declares no connections.
        self._register("changes_state")

        out, _err = self._run("changes_state")

        self.assertEqual(AlarmStateSnapshot.objects.get().current_state, AlarmState.ARMED_AWAY)
        self.assertEqual(self.published, [(AlarmState.ARMED_AWAY, True)])
        self.assertEqual([s["enabled"] for s in self.mqtt.applied], [True, False])
        self.assertFalse(self.mqtt.connected)
        self.assertIn("Published the alarm state (armed_away) to the Home Assistant alarm entity.", out)

    def test_reuses_the_mqtt_connection_the_task_declared(self):
        self._register("rule_task", connections=("mqtt", "zwavejs"))

        self._run("rule_task")

        self.assertEqual(self.published, [(AlarmState.ARMED_AWAY, True)])
        self.assertEqual([s["enabled"] for s in self.mqtt.applied], [True, False])

    def test_does_nothing_when_the_state_didnt_change(self):
        self._add_keypad()
        self._register("no_change", arms=False)

        out, err = self._run("no_change")

        self.assertEqual(self.published, [])
        self.assertEqual(self.mqtt.applied, [])
        self.assertNotIn("alarm state", out + err)

    def test_skips_the_publish_when_the_ha_alarm_entity_is_disabled(self):
        set_profile_settings(self.profile, home_assistant_alarm_entity={"enabled": False})
        self._register("changes_state")

        self._run("changes_state")

        self.assertEqual(self.published, [])
        self.assertEqual(self.mqtt.applied, [])

    def test_says_so_when_mqtt_doesnt_connect(self):
        self.mqtt._connects = False
        self._register("changes_state")

        _out, err = self._run("changes_state")

        self.assertEqual(self.published, [])
        self.assertIn("MQTT isn't connected, so the Home Assistant alarm entity didn't get the new alarm state.", err)
        self.assertEqual([s["enabled"] for s in self.mqtt.applied], [True, False])

    def test_says_so_when_mqtt_is_disabled(self):
        set_profile_settings(self.profile, mqtt={"enabled": False})
        self._register("changes_state")

        _out, err = self._run("changes_state")

        self.assertEqual(self.published, [])
        self.assertIn("MQTT is disabled, so the Home Assistant alarm entity didn't get the new alarm state.", err)

    def test_warns_that_the_keypads_dont_follow_and_doesnt_write_them(self):
        # The server's panel sync worker is the only keypad writer (ADR-0100), so this process mustn't be a second.
        self._add_keypad()
        self._register("changes_state", connections=("zwavejs",))

        _out, err = self._run("changes_state")

        self.assertIn(_KEYPAD_WARNING, err)

    def test_no_keypad_warning_without_enabled_keypads(self):
        self._register("changes_state")

        _out, err = self._run("changes_state")

        self.assertNotIn(_KEYPAD_WARNING, err)

    def test_still_publishes_when_the_task_fails_after_changing_the_state(self):
        self._add_keypad()
        self._register("fails", fails=True)

        out, err = StringIO(), StringIO()
        with self.assertRaisesMessage(CommandError, "boom"):
            call_command("run_task", "fails", stdout=out, stderr=err)

        self.assertEqual(self.published, [(AlarmState.ARMED_AWAY, True)])
        self.assertIn(_KEYPAD_WARNING, err.getvalue())
        self.assertFalse(self.mqtt.connected)

    def test_a_failed_follow_up_doesnt_hide_the_task_result(self):
        self._register("changes_state")

        with patch(
            "integrations_home_assistant.mqtt_alarm_entity.publish_state", side_effect=RuntimeError("broker gone")
        ):
            out, err = self._run("changes_state")

        self.assertIn("Task completed", out)
        self.assertIn("Couldn't follow up on the alarm state change (broker gone).", err)
        self.assertFalse(self.mqtt.connected)
