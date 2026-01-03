"""Tests for task runner."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

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
