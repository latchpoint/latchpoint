"""Management command to run a scheduled task manually."""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from scheduler import get_task, get_tasks


class Command(BaseCommand):
    """Run a scheduled task manually."""

    help = "Run a scheduled task manually"

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
            raise CommandError(
                f"Task '{task_name}' not found. Available tasks: {available or 'none'}"
            )

        self.stdout.write(f"Running task: {task_name}")
        start_time = time.monotonic()

        try:
            result = task.func()
            duration = time.monotonic() - start_time
            self.stdout.write(
                self.style.SUCCESS(f"Task completed in {duration:.2f}s")
            )
            if result is not None:
                self.stdout.write(f"Result: {result}")
        except Exception as e:
            duration = time.monotonic() - start_time
            raise CommandError(f"Task failed after {duration:.2f}s: {e}") from e
