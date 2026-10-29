"""Management command to run a scheduled task manually."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator

from django.core.management.base import BaseCommand, CommandError

from scheduler import get_task, get_tasks

# The HA alarm entity state publish after a task that changed the alarm state (#173).
_STATE_PUBLISH_ATTEMPTS = 2
_STATE_PUBLISH_TIMEOUT_SECONDS = 5.0


class Command(BaseCommand):
    """Run a scheduled task manually."""

    help = (
        "Run a scheduled task manually. MQTT and Z-Wave JS only stay connected in the server process, so a task "
        "that declares it needs one gets it opened for the run and closed again after. If the task changes the "
        "alarm state, the new state is published to the Home Assistant alarm entity, but the keypads only follow "
        "changes made in the server."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "task_name",
            type=str,
            help="Name of the task to run",
        )

    def handle(self, *args, **options) -> None:
        task_name = options["task_name"]
        task = get_task(task_name)

        if task is None:
            available = ", ".join(sorted(get_tasks().keys()))
            raise CommandError(f"Task '{task_name}' not found. Available tasks: {available or 'none'}")

        with self._connections(task.connections), self._follow_alarm_state(task.connections):
            self.stdout.write(f"Running task: {task_name}")
            start_time = time.monotonic()

            try:
                result = task.func()
                duration = time.monotonic() - start_time
                self.stdout.write(self.style.SUCCESS(f"Task completed in {duration:.2f}s"))
                if result is not None:
                    self.stdout.write(f"Result: {result}")
            except Exception as e:
                duration = time.monotonic() - start_time
                raise CommandError(f"Task failed after {duration:.2f}s: {e}") from e

    @contextlib.contextmanager
    def _connections(self, names: tuple[str, ...]) -> Iterator[None]:
        """
        Open the connections the task declares and close them when it's done (#164).

        The runtimes that hold them start only in the server, not here. Starting them all with
        START_RUNTIMES=true would also start a second scheduler, HA state stream and control panel listener in
        this process. A connection that's disabled or doesn't come up in time is reported and the task runs
        anyway, so it fails or skips the way it would in the server.
        """
        with contextlib.ExitStack() as stack:
            if "mqtt" in names:
                stack.enter_context(self._mqtt())
            if "zwavejs" in names:
                stack.enter_context(self._zwavejs())
            yield

    @contextlib.contextmanager
    def _follow_alarm_state(self, names: tuple[str, ...]) -> Iterator[None]:
        """
        Publish an alarm state change the task made to the HA alarm entity, and say the keypads won't follow (#173).

        The server's HA and control panel apps connect their `alarm_state_change_committed` receivers only in the
        server, so a change made here reaches neither. Publishing the retained state topic from here is safe, since it's
        the same idempotent publish the server makes, sent after the task with the state re-read from the DB (see
        `_publish_latest_alarm_state`).
        Writing the keypads isn't, since the server's panel sync worker owns every keypad write (ADR-0100).
        """
        from alarm.signals import alarm_state_change_committed

        changes: list[str] = []

        def _on_change(sender, *, state_to: str, **_kwargs) -> None:
            changes.append(state_to)

        dispatch_uid = f"run_task_follow_alarm_state_{id(self)}"
        alarm_state_change_committed.connect(_on_change, dispatch_uid=dispatch_uid, weak=False)
        try:
            yield
        finally:
            alarm_state_change_committed.disconnect(dispatch_uid=dispatch_uid)
            if changes:
                self._best_effort(lambda: self._publish_alarm_entity_state(mqtt_open="mqtt" in names))
                self._best_effort(self._warn_keypads_not_synced)

    def _best_effort(self, follow_up) -> None:
        # A failed follow-up is reported, and mustn't hide the task's own result or error.
        try:
            follow_up()
        except Exception as exc:
            self.stderr.write(f"Couldn't follow up on the alarm state change ({exc}).")

    def _publish_alarm_entity_state(self, *, mqtt_open: bool) -> None:
        from transports_mqtt.views import get_mqtt_settings

        from alarm.gateways.mqtt import default_mqtt_gateway
        from alarm.state_machine.settings import get_active_settings_profile, get_setting_json

        entity_settings = get_setting_json(get_active_settings_profile(), "home_assistant_alarm_entity") or {}
        if not isinstance(entity_settings, dict) or not entity_settings.get("enabled"):
            return
        if not get_mqtt_settings().get("enabled"):
            self.stderr.write("MQTT is disabled, so the Home Assistant alarm entity didn't get the new alarm state.")
            return

        with contextlib.nullcontext() if mqtt_open else self._mqtt():
            if not default_mqtt_gateway.get_status().connected:
                self.stderr.write(
                    "MQTT isn't connected, so the Home Assistant alarm entity didn't get the new alarm state. "
                    "The server publishes it on its next alarm state change or MQTT reconnect."
                )
                return

            try:
                published = self._publish_latest_alarm_state()
            except Exception as exc:
                self.stderr.write(f"Couldn't publish the new alarm state to the Home Assistant alarm entity ({exc}).")
                return
            self.stdout.write(f"Published the alarm state ({published}) to the Home Assistant alarm entity.")

    def _publish_latest_alarm_state(self) -> str:
        """
        Publish the alarm state from the DB to the HA alarm entity's retained state topic. Returns what it published.

        It publishes the state re-read from the DB rather than the task's changes, waits for the message to go out,
        then reads it once more and publishes again if it moved (at most `_STATE_PUBLISH_ATTEMPTS` publishes). The
        server publishes every change it commits, so this covers one it committed and published while ours was on its
        way, which would otherwise leave the broker holding our older state. What's left is a change the server
        commits after the last read here and whose publish reaches the broker before ours, which is the same race
        two threads in the server have. Raises if a publish fails or doesn't go out in time.
        """
        from integrations_home_assistant import mqtt_alarm_entity_status_store as status_store
        from integrations_home_assistant.mqtt_alarm_entity import STATE_TOPIC
        from transports_mqtt.manager import mqtt_connection_manager

        from alarm.state_machine.transitions import get_current_snapshot

        published: str | None = None
        for _ in range(_STATE_PUBLISH_ATTEMPTS):
            state = get_current_snapshot(process_timers=False).current_state
            if state == published:
                break
            info = mqtt_connection_manager.publish(topic=STATE_TOPIC, payload=state, retain=True)
            info.wait_for_publish(timeout=_STATE_PUBLISH_TIMEOUT_SECONDS)
            if not info.is_published():
                raise TimeoutError(f"it wasn't sent within {_STATE_PUBLISH_TIMEOUT_SECONDS:g}s")
            published = state

        with contextlib.suppress(Exception):
            status_store.mark_state_published()
        return published

    def _warn_keypads_not_synced(self) -> None:
        from control_panels.models import ControlPanelDevice

        if not ControlPanelDevice.objects.filter(enabled=True).exists():
            return
        self.stderr.write(
            "The alarm state changed in this process, but only the server's panel sync worker writes to the "
            "keypads, so they don't get this change. The server syncs them on its next alarm state change."
        )

    @contextlib.contextmanager
    def _mqtt(self) -> Iterator[None]:
        from transports_mqtt.views import get_mqtt_settings

        from alarm.gateways.mqtt import default_mqtt_gateway

        settings = get_mqtt_settings()
        if not settings.get("enabled"):
            self.stdout.write("MQTT is disabled, so the task runs without it.")
            yield
            return

        default_mqtt_gateway.apply_settings(settings=settings)
        try:
            timeout = float(settings.get("connect_timeout_seconds") or 5)
            deadline = time.monotonic() + timeout
            while not default_mqtt_gateway.get_status().connected and time.monotonic() < deadline:
                time.sleep(0.05)
            status = default_mqtt_gateway.get_status()
            if status.connected:
                self.stdout.write("Connected to MQTT for this run.")
            else:
                self.stderr.write(f"MQTT didn't connect within {timeout:g}s ({status.last_error or 'no error'}).")
            yield
        finally:
            default_mqtt_gateway.apply_settings(settings={**settings, "enabled": False})

    @contextlib.contextmanager
    def _zwavejs(self) -> Iterator[None]:
        from integrations_zwavejs.views import get_zwavejs_settings

        from alarm.gateways.zwavejs import default_zwavejs_gateway

        settings = get_zwavejs_settings()
        if not settings.get("enabled"):
            self.stdout.write("Z-Wave JS is disabled, so the task runs without it.")
            yield
            return

        # Without the node event bridges, so this connection doesn't feed node events to a rule dispatcher in this
        # process while the server's handles the same events.
        default_zwavejs_gateway.apply_settings(settings_obj=settings, event_bridges=False)
        try:
            timeout = float(settings.get("connect_timeout_seconds") or 5)
            try:
                default_zwavejs_gateway.ensure_connected(timeout_seconds=timeout)
                self.stdout.write("Connected to Z-Wave JS for this run.")
            except Exception as exc:
                self.stderr.write(f"Z-Wave JS didn't connect within {timeout:g}s ({exc}).")
            yield
        finally:
            default_zwavejs_gateway.apply_settings(settings_obj={**settings, "enabled": False}, event_bridges=False)
