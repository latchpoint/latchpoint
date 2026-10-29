"""Management command to run a scheduled task manually."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator

from django.core.management.base import BaseCommand, CommandError

from scheduler import get_task, get_tasks


class Command(BaseCommand):
    """Run a scheduled task manually."""

    help = (
        "Run a scheduled task manually. MQTT and Z-Wave JS only stay connected in the server process, so a task "
        "that declares it needs one gets it opened for the run and closed again after."
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

        with self._connections(task.connections):
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
