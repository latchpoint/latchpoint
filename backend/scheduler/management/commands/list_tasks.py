"""Management command to list registered scheduled tasks."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from scheduler import get_tasks
from scheduler.schedules import DailyAt, Every


class Command(BaseCommand):
    """List all registered scheduled tasks."""

    help = "List all registered scheduled tasks"

    def handle(self, *args, **options) -> None:
        tasks = get_tasks()

        if not tasks:
            self.stdout.write(self.style.WARNING("No tasks registered."))
            return

        self.stdout.write(self.style.SUCCESS(f"Registered tasks ({len(tasks)}):"))
        self.stdout.write("")

        for name, task in sorted(tasks.items()):
            status = self.style.SUCCESS("enabled") if task.enabled else self.style.ERROR("disabled")
            schedule_str = self._format_schedule(task.schedule)

            self.stdout.write(f"  {name}")
            self.stdout.write(f"    Schedule: {schedule_str}")
            self.stdout.write(f"    Status:   {status}")
            if task.max_runtime_seconds:
                self.stdout.write(f"    Max run:  {task.max_runtime_seconds}s")
            self.stdout.write(f"    Function: {task.func.__module__}.{task.func.__name__}")
            self.stdout.write("")

    def _format_schedule(self, schedule) -> str:
        """Format a schedule for display."""
        if isinstance(schedule, DailyAt):
            return f"Daily at {schedule.hour:02d}:{schedule.minute:02d}"
        elif isinstance(schedule, Every):
            if schedule.seconds >= 3600:
                hours = schedule.seconds / 3600
                interval = f"{hours:.1f} hours" if hours != int(hours) else f"{int(hours)} hours"
            elif schedule.seconds >= 60:
                minutes = schedule.seconds / 60
                interval = f"{minutes:.1f} minutes" if minutes != int(minutes) else f"{int(minutes)} minutes"
            else:
                interval = f"{schedule.seconds} seconds"

            jitter_str = f" (±{schedule.jitter}s jitter)" if schedule.jitter > 0 else ""
            return f"Every {interval}{jitter_str}"
        else:
            return str(schedule)
