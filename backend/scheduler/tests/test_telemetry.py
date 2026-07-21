from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

import scheduler.telemetry as telemetry_module
from scheduler.models import SchedulerTaskHealth
from scheduler.registry import ScheduledTask
from scheduler.schedules import DailyAt, Every


def _fast_task(name: str = "test_throttle_fast", *, seconds: int = 5) -> ScheduledTask:
    return ScheduledTask(name=name, func=lambda: None, schedule=Every(seconds=seconds))


class ShouldPersistHealthTests(SimpleTestCase):
    """ADR-0103: sub-minute tasks persist health at most once per ~60s window; other
    schedules and the first run always persist."""

    def setUp(self) -> None:
        telemetry_module._last_health_persist_at.clear()

    def tearDown(self) -> None:
        telemetry_module._last_health_persist_at.clear()

    def test_sub_minute_task_persists_once_per_window(self) -> None:
        task = _fast_task(seconds=5)
        with patch("scheduler.telemetry.time.monotonic", return_value=1000.0):
            self.assertTrue(telemetry_module.should_persist_health(task=task))  # first run
            self.assertFalse(telemetry_module.should_persist_health(task=task))  # within window
        with patch("scheduler.telemetry.time.monotonic", return_value=1000.0 + 61):
            self.assertTrue(telemetry_module.should_persist_health(task=task))  # window elapsed

    def test_long_interval_every_task_never_throttled(self) -> None:
        task = _fast_task(name="test_throttle_slow", seconds=120)
        self.assertTrue(telemetry_module.should_persist_health(task=task))
        self.assertTrue(telemetry_module.should_persist_health(task=task))
        self.assertTrue(telemetry_module.should_persist_health(task=task))

    def test_daily_task_never_throttled(self) -> None:
        task = ScheduledTask(name="test_throttle_daily", func=lambda: None, schedule=DailyAt(hour=3))
        self.assertTrue(telemetry_module.should_persist_health(task=task))
        self.assertTrue(telemetry_module.should_persist_health(task=task))


class FailureWriteNotThrottledTests(TestCase):
    """A failing run must persist its failure state even while the healthy-write window
    is active (failures are unconditional)."""

    def setUp(self) -> None:
        telemetry_module._last_health_persist_at.clear()

    def tearDown(self) -> None:
        telemetry_module._last_health_persist_at.clear()

    def test_failure_persists_while_healthy_writes_throttled(self) -> None:
        task = _fast_task(seconds=5)
        # Warm the window so a healthy persist would now be throttled.
        self.assertTrue(telemetry_module.should_persist_health(task=task))
        self.assertFalse(telemetry_module.should_persist_health(task=task))

        telemetry_module.update_task_health_finished_failure(
            task=task,
            finished_at=timezone.now(),
            duration_seconds=0.1,
            consecutive_failures=2,
            error_message="boom",
        )

        health = SchedulerTaskHealth.objects.get(task_name=task.name, instance_id="default")
        self.assertEqual(health.consecutive_failures, 2)
        self.assertFalse(health.is_running)
        self.assertEqual(health.last_error_message, "boom")


class GetInstanceIdTests(SimpleTestCase):
    """`get_instance_id()` must return the stable default with no override,
    and honor SCHEDULER_INSTANCE_ID when set. See ADR-0093."""

    def setUp(self) -> None:
        self._original_cache = telemetry_module._CACHED_INSTANCE_ID
        telemetry_module._CACHED_INSTANCE_ID = None

    def tearDown(self) -> None:
        telemetry_module._CACHED_INSTANCE_ID = self._original_cache

    @override_settings(SCHEDULER_INSTANCE_ID=None)
    def test_returns_default_when_no_override(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "default")

    @override_settings(SCHEDULER_INSTANCE_ID="")
    def test_returns_default_when_override_is_blank(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "default")

    @override_settings(SCHEDULER_INSTANCE_ID="replica-2")
    def test_uses_override_when_set(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "replica-2")

    @override_settings(SCHEDULER_INSTANCE_ID="  trimmed  ")
    def test_strips_override_whitespace(self) -> None:
        self.assertEqual(telemetry_module.get_instance_id(), "trimmed")

    @override_settings(SCHEDULER_INSTANCE_ID="cached-value")
    def test_result_is_cached(self) -> None:
        first = telemetry_module.get_instance_id()
        with override_settings(SCHEDULER_INSTANCE_ID="something-else"):
            second = telemetry_module.get_instance_id()
        self.assertEqual(first, second)
