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


class ShouldPersistFinishTests(SimpleTestCase):
    """ADR-0103: the throttle may skip a run's `started` write, so the supervisor persists
    is_running=True once a run is overdue. Those runs must always write their finish or the
    health row stays stuck at is_running=True."""

    def test_fast_run_does_not_force_a_finish_write(self) -> None:
        task = _fast_task(seconds=1)
        self.assertFalse(telemetry_module.should_persist_finish(task=task, duration_seconds=0.01))

    @override_settings(SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS=2.0)
    def test_slow_run_forces_a_finish_write(self) -> None:
        task = _fast_task(seconds=1)
        self.assertTrue(telemetry_module.should_persist_finish(task=task, duration_seconds=2.0))
        self.assertTrue(telemetry_module.should_persist_finish(task=task, duration_seconds=30.0))
        self.assertFalse(telemetry_module.should_persist_finish(task=task, duration_seconds=1.99))

    @override_settings(SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS=600.0)
    def test_overdue_run_forces_a_finish_write_even_when_under_slow_threshold(self) -> None:
        """The supervisor escalates on max_runtime_seconds, which can sit below the
        slow-run threshold — the finish must still persist or is_running=True sticks."""
        task = ScheduledTask(
            name="test_overdue_finish",
            func=lambda: None,
            schedule=Every(seconds=1),
            max_runtime_seconds=1,
        )
        self.assertFalse(telemetry_module.was_slow_run(duration_seconds=1.5))
        self.assertTrue(telemetry_module.should_persist_finish(task=task, duration_seconds=1.5))
        self.assertFalse(telemetry_module.should_persist_finish(task=task, duration_seconds=0.5))

    def test_no_max_runtime_falls_back_to_slow_threshold_only(self) -> None:
        task = _fast_task(seconds=1)
        self.assertIsNone(task.max_runtime_seconds)
        with override_settings(SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS=5.0):
            self.assertFalse(telemetry_module.should_persist_finish(task=task, duration_seconds=4.9))
            self.assertTrue(telemetry_module.should_persist_finish(task=task, duration_seconds=5.0))


class PersistRunningNowTests(TestCase):
    """The supervisor's escalation write makes a hung sub-minute task visible to the
    DB-derived running/stuck status in `scheduler/views.py`."""

    def setUp(self) -> None:
        telemetry_module._last_health_persist_at.clear()

    def tearDown(self) -> None:
        telemetry_module._last_health_persist_at.clear()

    def test_persists_is_running_with_started_at(self) -> None:
        task = ScheduledTask(
            name="test_escalated_running",
            func=lambda: None,
            schedule=Every(seconds=1),
            max_runtime_seconds=5,
        )
        started_at = timezone.now()

        telemetry_module.persist_running_now(task=task, started_at=started_at)

        health = SchedulerTaskHealth.objects.get(task_name=task.name, instance_id="default")
        self.assertTrue(health.is_running)
        self.assertEqual(health.last_started_at, started_at)
        self.assertEqual(health.max_runtime_seconds, 5)
        self.assertIsNotNone(health.last_heartbeat_at)

    def test_escalation_is_not_blocked_by_an_active_throttle_window(self) -> None:
        task = ScheduledTask(name="test_escalated_throttled", func=lambda: None, schedule=Every(seconds=1))
        # Warm the window so a healthy persist would now be throttled.
        self.assertTrue(telemetry_module.should_persist_health(task=task))
        self.assertFalse(telemetry_module.should_persist_health(task=task))

        telemetry_module.persist_running_now(task=task, started_at=timezone.now())

        health = SchedulerTaskHealth.objects.get(task_name=task.name, instance_id="default")
        self.assertTrue(health.is_running)


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
