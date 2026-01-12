"""Tests for door code event retention cleanup task."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from alarm.models import SystemConfig
from locks.models import DoorCodeEvent
from locks.tasks import cleanup_door_code_events


class CleanupDoorCodeEventsTests(TestCase):
    def test_disabled_retention_does_not_delete(self):
        now = timezone.now()
        SystemConfig.objects.create(
            key="door_code_events.retention_days",
            name="Door code event retention (days)",
            value_type="integer",
            value=0,
        )
        event = DoorCodeEvent.objects.create(
            door_code=None,
            user=None,
            lock_entity_id="",
            event_type=DoorCodeEvent.EventType.CODE_USED,
            metadata={},
        )
        DoorCodeEvent.objects.filter(pk=event.pk).update(created_at=now - timedelta(days=100))

        deleted = cleanup_door_code_events()

        self.assertEqual(deleted, 0)
        self.assertEqual(DoorCodeEvent.objects.count(), 1)

    def test_deletes_events_older_than_retention_and_keeps_boundary(self):
        fixed_now = timezone.now()
        SystemConfig.objects.create(
            key="door_code_events.retention_days",
            name="Door code event retention (days)",
            value_type="integer",
            value=90,
        )

        old = DoorCodeEvent.objects.create(
            door_code=None,
            user=None,
            lock_entity_id="",
            event_type=DoorCodeEvent.EventType.CODE_USED,
            metadata={},
        )
        boundary = DoorCodeEvent.objects.create(
            door_code=None,
            user=None,
            lock_entity_id="",
            event_type=DoorCodeEvent.EventType.CODE_USED,
            metadata={},
        )
        recent = DoorCodeEvent.objects.create(
            door_code=None,
            user=None,
            lock_entity_id="",
            event_type=DoorCodeEvent.EventType.CODE_USED,
            metadata={},
        )

        cutoff = fixed_now - timedelta(days=90)
        DoorCodeEvent.objects.filter(pk=old.pk).update(created_at=cutoff - timedelta(seconds=1))
        DoorCodeEvent.objects.filter(pk=boundary.pk).update(created_at=cutoff)
        DoorCodeEvent.objects.filter(pk=recent.pk).update(created_at=cutoff + timedelta(seconds=1))

        with patch("locks.tasks.timezone.now", return_value=fixed_now):
            deleted = cleanup_door_code_events()

        self.assertEqual(deleted, 1)
        self.assertEqual(DoorCodeEvent.objects.count(), 2)
        self.assertTrue(DoorCodeEvent.objects.filter(pk=boundary.pk).exists())
        self.assertTrue(DoorCodeEvent.objects.filter(pk=recent.pk).exists())

