"""Tests for session cleanup task."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone

from alarm.tasks import cleanup_expired_sessions


class CleanupExpiredSessionsTests(TestCase):
    def test_deletes_expired_sessions(self):
        now = timezone.now()

        Session.objects.create(
            session_key="expired-1",
            session_data="test",
            expire_date=now - timedelta(days=1),
        )
        Session.objects.create(
            session_key="expired-2",
            session_data="test",
            expire_date=now - timedelta(seconds=1),
        )
        Session.objects.create(
            session_key="active-1",
            session_data="test",
            expire_date=now + timedelta(days=1),
        )

        deleted = cleanup_expired_sessions()

        self.assertEqual(deleted, 2)
        self.assertEqual(Session.objects.count(), 1)
        self.assertEqual(Session.objects.first().session_key, "active-1")

    def test_returns_zero_when_no_expired_sessions(self):
        now = timezone.now()

        Session.objects.create(
            session_key="active-1",
            session_data="test",
            expire_date=now + timedelta(days=1),
        )

        deleted = cleanup_expired_sessions()

        self.assertEqual(deleted, 0)
        self.assertEqual(Session.objects.count(), 1)

