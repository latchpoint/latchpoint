"""Tests for schedule types."""

from __future__ import annotations

from django.test import TestCase

from scheduler.schedules import DailyAt, Every, Schedule


class ScheduleTypesTests(TestCase):
    def test_daily_at_defaults(self):
        """DailyAt has sensible defaults (3:00 AM)."""
        schedule = DailyAt()
        self.assertEqual(schedule.hour, 3)
        self.assertEqual(schedule.minute, 0)

    def test_daily_at_custom_time(self):
        """DailyAt accepts custom hour and minute."""
        schedule = DailyAt(hour=14, minute=30)
        self.assertEqual(schedule.hour, 14)
        self.assertEqual(schedule.minute, 30)

    def test_daily_at_inherits_schedule(self):
        """DailyAt is a Schedule subclass."""
        schedule = DailyAt()
        self.assertIsInstance(schedule, Schedule)

    def test_every_defaults(self):
        """Every has sensible defaults (1 hour, no jitter)."""
        schedule = Every()
        self.assertEqual(schedule.seconds, 3600)
        self.assertEqual(schedule.jitter, 0)

    def test_every_custom_interval(self):
        """Every accepts custom interval."""
        schedule = Every(seconds=300)
        self.assertEqual(schedule.seconds, 300)

    def test_every_with_jitter(self):
        """Every accepts jitter for randomization."""
        schedule = Every(seconds=60, jitter=10)
        self.assertEqual(schedule.seconds, 60)
        self.assertEqual(schedule.jitter, 10)

    def test_every_inherits_schedule(self):
        """Every is a Schedule subclass."""
        schedule = Every()
        self.assertIsInstance(schedule, Schedule)
