"""Tests for task registry."""

from __future__ import annotations

from django.test import TestCase

from scheduler.registry import (
    ScheduledTask,
    _tasks,
    get_task,
    get_tasks,
    register,
)
from scheduler.schedules import DailyAt, Every


class RegistryTests(TestCase):
    def setUp(self):
        """Clear the task registry before each test."""
        _tasks.clear()

    def tearDown(self):
        """Clear the task registry after each test."""
        _tasks.clear()

    def test_register_decorator_adds_task(self):
        """@register decorator adds task to registry."""

        @register("test_task", schedule=DailyAt(hour=5))
        def my_task():
            pass

        tasks = get_tasks()
        self.assertIn("test_task", tasks)
        self.assertEqual(tasks["test_task"].name, "test_task")
        self.assertEqual(tasks["test_task"].func, my_task)

    def test_register_preserves_function(self):
        """@register returns the original function unchanged."""

        @register("another_task", schedule=Every(seconds=60))
        def my_func():
            return 42

        # Function should still work normally
        self.assertEqual(my_func(), 42)

    def test_register_with_enabled_false(self):
        """Tasks can be registered as disabled."""

        @register("disabled_task", schedule=DailyAt(), enabled=False)
        def disabled_func():
            pass

        task = get_task("disabled_task")
        self.assertIsNotNone(task)
        self.assertFalse(task.enabled)

    def test_register_applies_settings_overrides(self):
        """register() applies settings SCHEDULER_TASK_OVERRIDES."""
        with self.settings(
            SCHEDULER_TASK_OVERRIDES={
                "overridden": {
                    "enabled": False,
                    "max_runtime_seconds": 12,
                    "failure_backoff_base_seconds": 5,
                    "failure_backoff_max_seconds": 60,
                    "failure_suspend_after": 3,
                    "failure_suspend_seconds": 600,
                }
            }
        ):

            @register("overridden", schedule=DailyAt())
            def overridden():
                pass

        task = get_task("overridden")
        self.assertIsNotNone(task)
        self.assertFalse(task.enabled)
        self.assertEqual(task.max_runtime_seconds, 12)
        self.assertEqual(task.failure_backoff_base_seconds, 5)
        self.assertEqual(task.failure_backoff_max_seconds, 60)
        self.assertEqual(task.failure_suspend_after, 3)
        self.assertEqual(task.failure_suspend_seconds, 600)

    def test_get_tasks_returns_copy(self):
        """get_tasks returns a copy, not the original dict."""

        @register("task1", schedule=DailyAt())
        def task1():
            pass

        tasks1 = get_tasks()
        tasks2 = get_tasks()

        self.assertEqual(tasks1, tasks2)
        self.assertIsNot(tasks1, tasks2)

        # Modifying returned dict doesn't affect registry
        tasks1["fake"] = None
        self.assertNotIn("fake", get_tasks())

    def test_get_task_returns_none_for_unknown(self):
        """get_task returns None for non-existent tasks."""
        self.assertIsNone(get_task("nonexistent"))

    def test_get_task_returns_task(self):
        """get_task returns the registered task."""

        @register("findable", schedule=Every(seconds=30))
        def findable():
            pass

        task = get_task("findable")
        self.assertIsNotNone(task)
        self.assertEqual(task.name, "findable")

    def test_scheduled_task_dataclass(self):
        """ScheduledTask holds all required fields."""

        def sample():
            pass

        schedule = DailyAt(hour=12, minute=30)
        task = ScheduledTask(
            name="sample_task",
            func=sample,
            schedule=schedule,
            enabled=True,
        )

        self.assertEqual(task.name, "sample_task")
        self.assertEqual(task.func, sample)
        self.assertEqual(task.schedule, schedule)
        self.assertTrue(task.enabled)

    def test_multiple_tasks_registered(self):
        """Multiple tasks can be registered."""

        @register("task_a", schedule=DailyAt(hour=1))
        def task_a():
            pass

        @register("task_b", schedule=Every(seconds=120))
        def task_b():
            pass

        @register("task_c", schedule=DailyAt(hour=23, minute=59))
        def task_c():
            pass

        tasks = get_tasks()
        self.assertEqual(len(tasks), 3)
        self.assertIn("task_a", tasks)
        self.assertIn("task_b", tasks)
        self.assertIn("task_c", tasks)
