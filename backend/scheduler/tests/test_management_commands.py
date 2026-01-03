"""Tests for scheduler management commands."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from scheduler.registry import _tasks, register
from scheduler.schedules import DailyAt, Every


class ListTasksCommandTests(TestCase):
    def setUp(self):
        """Clear the task registry before each test."""
        _tasks.clear()

    def tearDown(self):
        """Clear the task registry after each test."""
        _tasks.clear()

    def test_list_tasks_empty(self):
        """Shows message when no tasks registered."""
        out = StringIO()
        call_command("list_tasks", stdout=out)
        self.assertIn("No tasks registered", out.getvalue())

    def test_list_tasks_shows_registered(self):
        """Lists registered tasks with details."""

        @register("my_daily_task", schedule=DailyAt(hour=5, minute=30))
        def my_daily_task():
            pass

        out = StringIO()
        call_command("list_tasks", stdout=out)

        output = out.getvalue()
        self.assertIn("my_daily_task", output)
        self.assertIn("Daily at 05:30", output)
        self.assertIn("enabled", output)

    def test_list_tasks_shows_every_schedule(self):
        """Shows Every schedule formatted nicely."""

        @register("frequent_task", schedule=Every(seconds=300))
        def frequent_task():
            pass

        out = StringIO()
        call_command("list_tasks", stdout=out)

        output = out.getvalue()
        self.assertIn("frequent_task", output)
        self.assertIn("Every 5 minutes", output)

    def test_list_tasks_shows_disabled(self):
        """Shows disabled status for disabled tasks."""

        @register("disabled_task", schedule=DailyAt(), enabled=False)
        def disabled_task():
            pass

        out = StringIO()
        call_command("list_tasks", stdout=out)

        output = out.getvalue()
        self.assertIn("disabled_task", output)
        self.assertIn("disabled", output)


class RunTaskCommandTests(TestCase):
    def setUp(self):
        """Clear the task registry before each test."""
        _tasks.clear()

    def tearDown(self):
        """Clear the task registry after each test."""
        _tasks.clear()

    def test_run_task_not_found(self):
        """Raises error for unknown task."""
        with self.assertRaises(CommandError) as ctx:
            call_command("run_task", "nonexistent")
        self.assertIn("not found", str(ctx.exception))

    def test_run_task_executes(self):
        """Runs the task function."""
        executed = []

        @register("trackable", schedule=DailyAt())
        def trackable():
            executed.append(True)
            return 42

        out = StringIO()
        call_command("run_task", "trackable", stdout=out)

        self.assertEqual(executed, [True])
        self.assertIn("completed", out.getvalue())
        self.assertIn("42", out.getvalue())

    def test_run_task_reports_error(self):
        """Reports error when task fails."""

        @register("failing", schedule=DailyAt())
        def failing():
            raise ValueError("Something went wrong")

        with self.assertRaises(CommandError) as ctx:
            call_command("run_task", "failing")

        self.assertIn("failed", str(ctx.exception))
        self.assertIn("Something went wrong", str(ctx.exception))


class TaskScheduleCommandTests(TestCase):
    def setUp(self):
        """Clear the task registry before each test."""
        _tasks.clear()

    def tearDown(self):
        """Clear the task registry after each test."""
        _tasks.clear()

    def test_task_schedule_empty(self):
        """Shows message when no tasks registered."""
        out = StringIO()
        call_command("task_schedule", stdout=out)
        self.assertIn("No tasks registered", out.getvalue())

    def test_task_schedule_shows_next_run(self):
        """Shows next run time for tasks."""

        @register("scheduled_task", schedule=DailyAt(hour=3, minute=0))
        def scheduled_task():
            pass

        out = StringIO()
        call_command("task_schedule", stdout=out)

        output = out.getvalue()
        self.assertIn("scheduled_task", output)
        self.assertIn("Next run:", output)
        self.assertIn("Daily at 03:00", output)
