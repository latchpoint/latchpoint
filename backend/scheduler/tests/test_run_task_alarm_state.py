"""`manage.py run_task` publishes an alarm state change to the HA alarm entity, and never writes the keypads (#173)."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from integrations_home_assistant.mqtt_alarm_entity import STATE_TOPIC
from transports_mqtt.manager import MqttNotReachable, mqtt_connection_manager

from alarm.models import AlarmState, AlarmStateSnapshot
from alarm.state_machine import transitions
from alarm.tests.settings_test_utils import EncryptionTestMixin, set_profile_settings
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from control_panels.models import ControlPanelDevice, ControlPanelIntegrationType, ControlPanelKind
from scheduler import Every, register, registry
from scheduler.tests.test_run_task_connections import _FakeMqttGateway, _FakeZwavejsGateway

_KEYPAD_WARNING = "only the server's panel sync worker writes to the keypads"


class _FakeMessageInfo:
    """Stands in for paho's `MQTTMessageInfo`."""

    def __init__(self, *, sent: bool) -> None:
        self._sent = sent
        self.waited_for: float | None = None

    def wait_for_publish(self, timeout: float | None = None) -> None:
        self.waited_for = timeout

    def is_published(self) -> bool:
        return self._sent


def _set_alarm_state(state: str) -> None:
    """Change the snapshot without the signal, like a commit in the server process would look from here."""
    AlarmStateSnapshot.objects.update(current_state=state)


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

        # (payload, whether MQTT was connected) for each retained state publish through the manager.
        self.published: list[tuple[str, bool]] = []
        # Runs after each publish, ie to stand in for the server committing a change while ours is on its way.
        self.after_publish = None
        self.sends = True

        def _publish(*, topic: str, payload: str, qos: int = 0, retain: bool = False):
            self.assertEqual((topic, retain), (STATE_TOPIC, True))
            self.published.append((payload, self.mqtt.connected))
            if self.after_publish is not None:
                self.after_publish()
            return _FakeMessageInfo(sent=self.sends)

        publish_patch = patch.object(mqtt_connection_manager, "publish", side_effect=_publish)
        self.publish = publish_patch.start()
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

    def _register(
        self,
        name: str,
        *,
        connections: tuple[str, ...] = (),
        arms: bool = True,
        fails: bool = False,
        then_server_sets: str | None = None,
    ):
        @register(name, schedule=Every(seconds=60), connections=connections)
        def _task():
            if arms:
                # The commit runs the `alarm_state_change_committed` receivers, like a real task's would.
                with self.captureOnCommitCallbacks(execute=True):
                    transitions.arm(target_state=AlarmState.ARMED_AWAY, reason="test")
            if then_server_sets is not None:
                _set_alarm_state(then_server_sets)
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
        self.assertEqual(self.publish.call_count, 1)

    def test_publishes_the_state_read_after_the_task_not_the_tasks_change(self):
        # The task committed armed_away, then the server disarmed before the follow-up read the snapshot.
        self._register("changes_state", then_server_sets=AlarmState.DISARMED)

        out, _err = self._run("changes_state")

        self.assertEqual(self.published, [(AlarmState.DISARMED, True)])
        self.assertIn("Published the alarm state (disarmed)", out)

    def test_republishes_when_the_state_moved_while_the_publish_was_on_its_way(self):
        # The server commits (and publishes) disarmed after our read, so our armed_away could land after its message
        # and stay retained. The re-read after our publish catches it.
        self.after_publish = lambda: _set_alarm_state(AlarmState.DISARMED) if len(self.published) == 1 else None
        self._register("changes_state")

        out, _err = self._run("changes_state")

        self.assertEqual(self.published, [(AlarmState.ARMED_AWAY, True), (AlarmState.DISARMED, True)])
        self.assertIn("Published the alarm state (disarmed)", out)

    def test_publishes_at_most_twice(self):
        states = iter([AlarmState.DISARMED, AlarmState.ARMED_HOME, AlarmState.TRIGGERED])
        self.after_publish = lambda: _set_alarm_state(next(states))
        self._register("changes_state")

        self._run("changes_state")

        self.assertEqual([state for state, _ in self.published], [AlarmState.ARMED_AWAY, AlarmState.DISARMED])

    def test_says_so_when_the_publish_doesnt_go_out(self):
        self.sends = False
        self._register("changes_state")

        out, err = self._run("changes_state")

        self.assertNotIn("Published the alarm state", out)
        self.assertIn(
            "Couldn't publish the new alarm state to the Home Assistant alarm entity (it wasn't sent within 5s).", err
        )

    def test_says_so_when_the_manager_refuses_the_publish(self):
        # `publish_state` used to swallow this and the command still printed "Published".
        self.publish.side_effect = MqttNotReachable("MQTT is not connected.")
        self._register("changes_state")

        out, err = self._run("changes_state")

        self.assertNotIn("Published the alarm state", out)
        self.assertIn(
            "Couldn't publish the new alarm state to the Home Assistant alarm entity (MQTT is not connected.)", err
        )
        self.assertIn("Task completed", out)
        self.assertFalse(self.mqtt.connected)

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

    def test_a_failed_follow_up_doesnt_hide_the_task_result_or_skip_the_other(self):
        self._add_keypad()
        self._register("changes_state")

        with patch(
            "scheduler.management.commands.run_task.Command._publish_alarm_entity_state",
            side_effect=RuntimeError("settings unreadable"),
        ):
            out, err = self._run("changes_state")

        self.assertIn("Task completed", out)
        self.assertIn("Couldn't follow up on the alarm state change (settings unreadable).", err)
        self.assertIn(_KEYPAD_WARNING, err)
