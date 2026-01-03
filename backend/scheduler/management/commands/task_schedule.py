"""Management command to show next scheduled runs for tasks."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from scheduler import get_tasks
from scheduler.runner import _compute_next_run
from scheduler.schedules import DailyAt, Every


class Command(BaseCommand):
    """Show the next scheduled run time for all tasks."""

    help = "Show the next scheduled run time for all tasks"

    def handle(self, *args, **options) -> None:
        tasks = get_tasks()

        if not tasks:
            self.stdout.write(self.style.WARNING("No tasks registered."))
            return

        now = timezone.now()
        self.stdout.write(f"Current time: {now.isoformat()}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Upcoming task runs:"))
        self.stdout.write("")

        # Sort by next run time
        task_runs = []
        for name, task in tasks.items():
            if not task.enabled:
                continue
            next_run = _compute_next_run(task.schedule, now)
            task_runs.append((next_run, name, task))

        task_runs.sort(key=lambda x: x[0])

        for next_run, name, task in task_runs:
            time_until = next_run - now
            hours, remainder = divmod(int(time_until.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)

            if hours > 0:
                time_str = f"{hours}h {minutes}m"
            elif minutes > 0:
                time_str = f"{minutes}m {seconds}s"
            else:
                time_str = f"{seconds}s"

            schedule_str = self._format_schedule(task.schedule)
            self.stdout.write(f"  {name}")
            self.stdout.write(f"    Next run: {next_run.isoformat()} (in {time_str})")
            self.stdout.write(f"    Schedule: {schedule_str}")
            self.stdout.write("")

        # Show disabled tasks
        disabled = [name for name, task in tasks.items() if not task.enabled]
        if disabled:
            self.stdout.write(self.style.WARNING("Disabled tasks:"))
            for name in sorted(disabled):
                self.stdout.write(f"  {name}")

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
