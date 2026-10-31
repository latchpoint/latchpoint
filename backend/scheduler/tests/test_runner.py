"""Tests for task runner."""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

import scheduler.runner as runner
import scheduler.telemetry as telemetry_module
from scheduler.models import SchedulerTaskHealth
from scheduler.registry import ScheduledTask
from scheduler.runner import _compute_next_run, get_scheduler_status
from scheduler.schedules import DailyAt, Every


class ComputeNextRunTests(TestCase):
    def test_daily_at_future_today(self):
        """DailyAt schedules for later today if time hasn't passed."""
        now = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        schedule = DailyAt(hour=14, minute=30)

        next_run = _compute_next_run(schedule, now)

        self.assertEqual(next_run.hour, 14)
        self.assertEqual(next_run.minute, 30)
        self.assertEqual(next_run.date(), now.date())

    def test_daily_at_tomorrow(self):
        """DailyAt schedules for tomorrow if time has passed."""
        now = timezone.now().replace(hour=16, minute=0, second=0, microsecond=0)
        schedule = DailyAt(hour=14, minute=30)

        next_run = _compute_next_run(schedule, now)

        self.assertEqual(next_run.hour, 14)
        self.assertEqual(next_run.minute, 30)
        self.assertEqual(next_run.date(), now.date() + timedelta(days=1))

    def test_daily_at_exactly_now(self):
        """DailyAt schedules for tomorrow if exactly at scheduled time."""
        now = timezone.now().replace(hour=14, minute=30, second=0, microsecond=0)
        schedule = DailyAt(hour=14, minute=30)

        next_run = _compute_next_run(schedule, now)

        # Should schedule for tomorrow since now <= next_run triggers tomorrow
        self.assertEqual(next_run.date(), now.date() + timedelta(days=1))

    def test_every_simple_interval(self):
        """Every schedules for now + seconds."""
        now = timezone.now()
        schedule = Every(seconds=300)

        next_run = _compute_next_run(schedule, now)

        expected = now + timedelta(seconds=300)
        self.assertEqual(next_run, expected)

    def test_every_with_jitter(self):
        """Every with jitter adds random time within jitter range."""
        now = timezone.now()
        schedule = Every(seconds=60, jitter=10)

        with patch("scheduler.runner.random.randint", return_value=5):
            next_run = _compute_next_run(schedule, now)

        expected = now + timedelta(seconds=65)  # 60 + 5 jitter
        self.assertEqual(next_run, expected)

    def test_every_with_negative_jitter(self):
        """Every with jitter can run earlier (negative jitter offset)."""
        now = timezone.now()
        schedule = Every(seconds=60, jitter=10)

        with patch("scheduler.runner.random.randint", return_value=-5):
            next_run = _compute_next_run(schedule, now)

        expected = now + timedelta(seconds=55)  # 60 - 5 jitter
        self.assertEqual(next_run, expected)

    def test_every_zero_jitter(self):
        """Every with zero jitter doesn't add randomness."""
        now = timezone.now()
        schedule = Every(seconds=120, jitter=0)

        next_run = _compute_next_run(schedule, now)

        expected = now + timedelta(seconds=120)
        self.assertEqual(next_run, expected)

    def test_unknown_schedule_raises(self):
        """Unknown schedule types raise ValueError."""

        class UnknownSchedule:
            pass

        now = timezone.now()

        with self.assertRaises(ValueError) as ctx:
            _compute_next_run(UnknownSchedule(), now)

        self.assertIn("Unknown schedule type", str(ctx.exception))


class SchedulerStatusTests(TestCase):
    def test_get_scheduler_status_structure(self):
        """get_scheduler_status returns expected structure."""
        status = get_scheduler_status()

        self.assertIn("running", status)
        self.assertIn("tasks", status)
        self.assertIsInstance(status["running"], bool)
        self.assertIsInstance(status["tasks"], dict)


class RunnerThrottledFinishTests(TransactionTestCase):
    """ADR-0103: the supervisor persists is_running=True for an overdue run whose `started`
    write the throttle skipped, so a throttled run that turns out to be slow must still
    write its finish — otherwise the health row stays stuck at is_running=True.

    TransactionTestCase: `_run_task_loop` calls `close_old_connections()`, which closes the
    connection inside TestCase's transaction on Postgres (a no-op on in-memory SQLite)."""

    def setUp(self) -> None:
        telemetry_module._last_health_persist_at.clear()
        self._name = "test_throttled_finish"

    def tearDown(self) -> None:
        telemetry_module._last_health_persist_at.clear()
        with runner._lock:
            runner._running.discard(self._name)
            runner._task_status.pop(self._name, None)
            runner._threads.pop(self._name, None)
            runner._stop_events.pop(self._name, None)

    def _run_one_throttled_pass(self) -> None:
        """Drive a single run whose health writes are already inside the throttle window."""
        stop_event = threading.Event()
        task = ScheduledTask(name=self._name, func=stop_event.set, schedule=Every(seconds=0))
        # Consume the window so `_run_task_loop`'s own call returns False for this run.
        self.assertTrue(telemetry_module.should_persist_health(task=task))
        runner._run_task_loop(task=task, stop_event=stop_event)

    @override_settings(SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS=0.0)
    def test_throttled_slow_run_still_persists_its_finish(self) -> None:
        self._run_one_throttled_pass()

        health = SchedulerTaskHealth.objects.get(task_name=self._name, instance_id="default")
        self.assertFalse(health.is_running)
        self.assertIsNotNone(health.last_finished_at)

    @override_settings(SCHEDULER_SLOW_RUN_THRESHOLD_SECONDS=600.0)
    def test_throttled_fast_run_writes_no_health(self) -> None:
        """The quiet-down still holds for healthy fast runs — only the registration row
        written at loop start is present, with no per-run health writes."""
        self._run_one_throttled_pass()

        health = SchedulerTaskHealth.objects.get(task_name=self._name, instance_id="default")
        self.assertFalse(health.is_running)
        self.assertIsNone(health.last_finished_at)
        self.assertIsNone(health.last_started_at)
        self.assertIsNone(health.next_run_at)


class WakeTaskTests(TestCase):
    """Issue #124: ``wake_task`` runs a task before its next scheduled time.

    The loop runs in a real thread with the telemetry writes turned off, so it
    never touches the DB. Every wait has a timeout so a regression fails
    instead of hanging.
    """

    TIMEOUT = 5.0

    def setUp(self) -> None:
        self._name = "test_wake_task"
        self.runs = 0
        self.ran = threading.Event()
        self.release = threading.Event()
        self.release.set()
        patcher = patch.object(runner, "_safe_telemetry", lambda *args, **kwargs: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        with runner._lock:
            stop = runner._stop_events.get(self._name)
            wake = runner._wake_events.get(self._name)
        for event in (stop, wake, self.release):
            if event is not None:
                event.set()
        thread = runner._threads.get(self._name)
        if thread is not None:
            thread.join(timeout=self.TIMEOUT)
        with runner._lock:
            for registry in (runner._threads, runner._stop_events, runner._wake_events, runner._task_status):
                registry.pop(self._name, None)
            runner._running.discard(self._name)

    def _func(self) -> None:
        self.runs += 1
        self.ran.set()
        self.release.wait(timeout=self.TIMEOUT)

    def _start(self, **task_kwargs) -> threading.Thread:
        task = ScheduledTask(name=self._name, func=self._func, schedule=Every(seconds=3600), **task_kwargs)
        stop_event, wake_event = threading.Event(), threading.Event()
        thread = threading.Thread(
            target=runner._run_task_loop,
            kwargs={"task": task, "stop_event": stop_event, "wake_event": wake_event},
            daemon=True,
        )
        with runner._lock:
            runner._threads[self._name] = thread
            runner._stop_events[self._name] = stop_event
            runner._wake_events[self._name] = wake_event
        thread.start()
        return thread

    def _wait_until_sleeping(self) -> None:
        """Until the loop has scheduled its next run, ie it's waiting."""
        deadline = time.monotonic() + self.TIMEOUT
        while time.monotonic() < deadline:
            with runner._lock:
                if runner._task_status.get(self._name, {}).get("next_run_at"):
                    return
            time.sleep(0.01)
        self.fail("the task loop never started waiting")

    def test_a_wake_runs_the_task_long_before_its_next_scheduled_time(self):
        self._start()
        self._wait_until_sleeping()

        self.assertTrue(runner.wake_task(self._name))

        self.assertTrue(self.ran.wait(timeout=self.TIMEOUT))
        self.assertEqual(self.runs, 1)

    def test_a_wake_during_a_run_gets_exactly_one_more_run(self):
        self.release.clear()
        self._start()
        self._wait_until_sleeping()
        runner.wake_task(self._name)
        self.assertTrue(self.ran.wait(timeout=self.TIMEOUT))
        self.ran.clear()

        # Mid-run: the event was cleared right before the run, so this one sticks.
        self.assertTrue(runner.wake_task(self._name))
        self.assertTrue(runner.wake_task(self._name))
        self.release.set()

        self.assertTrue(self.ran.wait(timeout=self.TIMEOUT))
        self.ran.clear()
        # Two wakes during one run are one more run, not two.
        self.assertFalse(self.ran.wait(timeout=0.3))
        self.assertEqual(self.runs, 2)

    def test_a_wake_doesnt_cut_a_failure_backoff_short(self):
        with runner._lock:
            runner._task_status[self._name] = {"consecutive_failures": 1}
        thread = self._start(failure_backoff_base_seconds=3600)
        self._wait_until_sleeping()

        self.assertTrue(runner.wake_task(self._name))

        self.assertFalse(self.ran.wait(timeout=0.3))
        # Only a stop ends a backoff early.
        with runner._lock:
            runner._stop_task_locked(self._name)
        thread.join(timeout=self.TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.runs, 0)

    def test_stopping_a_task_ends_its_wait_on_the_wake_event(self):
        thread = self._start()
        self._wait_until_sleeping()

        with runner._lock:
            runner._stop_task_locked(self._name)
            self.assertTrue(runner._wake_events[self._name].is_set())

        thread.join(timeout=self.TIMEOUT)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.runs, 0)
        self.assertFalse(runner.is_task_running(self._name))
        self.assertFalse(runner.wake_task(self._name))

    def test_is_task_running_only_for_a_live_loop_that_isnt_stopping(self):
        self.assertFalse(runner.is_task_running(self._name))
        self._start()
        self.assertTrue(runner.is_task_running(self._name))

    def test_wake_is_a_noop_in_a_process_without_the_task(self):
        self.assertFalse(runner.wake_task("not_a_registered_task"))
        self.assertFalse(runner.is_task_running("not_a_registered_task"))
        self.assertNotIn("not_a_registered_task", runner._wake_events)

    def test_the_scheduler_gives_each_task_a_wake_event(self):
        task = ScheduledTask(name=self._name, func=self._func, schedule=Every(seconds=3600))
        started: list[dict] = []

        class _Thread:
            def __init__(self, *, target, name, daemon, kwargs=None):
                started.append(kwargs or {})

            def start(self):
                pass

            def is_alive(self):
                return True

            def join(self, timeout=None):
                pass

        with (
            patch.object(runner, "_watchdog_started", False),
            patch.object(runner, "get_tasks", return_value={self._name: task}),
            patch.object(runner.threading, "Thread", _Thread),
        ):
            runner.start_scheduler()

        task_kwargs = next(k for k in started if k.get("task") is task)
        self.assertIs(runner._wake_events[self._name], task_kwargs["wake_event"])
        self.assertTrue(runner.is_task_running(self._name))


class RunnerLogLevelTests(TransactionTestCase):
    """ADR-0103: the three per-run runner log lines (scheduled / starting / completed)
    drop to DEBUG so healthy no-op runs are silent at INFO.

    TransactionTestCase: `_run_task_loop` calls `close_old_connections()`, which closes the
    connection inside TestCase's transaction on Postgres (a no-op on in-memory SQLite)."""

    def setUp(self) -> None:
        telemetry_module._last_health_persist_at.clear()
        self._name = "test_log_demotion"

    def tearDown(self) -> None:
        telemetry_module._last_health_persist_at.clear()
        with runner._lock:
            runner._running.discard(self._name)
            runner._task_status.pop(self._name, None)
            runner._threads.pop(self._name, None)
            runner._stop_events.pop(self._name, None)

    def test_healthy_run_emits_no_info_per_run_lines(self):
        stop_event = threading.Event()
        runs: list[int] = []

        def _func() -> None:
            runs.append(1)
            stop_event.set()  # end the loop after a single healthy run

        task = ScheduledTask(name=self._name, func=_func, schedule=Every(seconds=0))

        with self.assertLogs("scheduler.runner", level="DEBUG") as cm:
            runner._run_task_loop(task=task, stop_event=stop_event)

        self.assertEqual(len(runs), 1)

        per_run_prefixes = (
            f"Task {self._name} scheduled",
            f"Task {self._name} starting",
            f"Task {self._name} completed",
        )
        info_offenders = [
            r.getMessage()
            for r in cm.records
            if r.levelno == logging.INFO and r.getMessage().startswith(per_run_prefixes)
        ]
        # The three per-run lines must not appear at INFO (only the test-induced
        # "stopping" line does, which never occurs during steady-state operation).
        self.assertEqual(info_offenders, [])

        debug_msgs = [r.getMessage() for r in cm.records if r.levelno == logging.DEBUG]
        self.assertTrue(any(m.startswith(f"Task {self._name} scheduled") for m in debug_msgs))
        self.assertIn(f"Task {self._name} starting", debug_msgs)
        self.assertTrue(any(m.startswith(f"Task {self._name} completed") for m in debug_msgs))
