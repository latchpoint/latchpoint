"""Tests for Frigate detection cleanup task."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmSettingsEntry, AlarmSettingsProfile
from integrations_frigate.models import FrigateDetection
from integrations_frigate.tasks import cleanup_frigate_detections


class FrigateCleanupTaskTests(TestCase):
    def setUp(self):
        self.profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)

    def _set_frigate_settings(self, *, enabled: bool, retention_seconds: int = 3600):
        AlarmSettingsEntry.objects.update_or_create(
            profile=self.profile,
            key="frigate",
            defaults={
                "value_type": "json",
                "value": {
                    "enabled": enabled,
                    "events_topic": "frigate/events",
                    "retention_seconds": retention_seconds,
                },
            },
        )

    def test_cleanup_deletes_old_detections(self):
        """Detections older than retention_seconds should be deleted."""
        self._set_frigate_settings(enabled=True, retention_seconds=3600)

        now = timezone.now()

        # Create an old detection (2 hours ago)
        old_detection = FrigateDetection.objects.create(
            provider="frigate",
            event_id="old-event",
            label="person",
            camera="backyard",
            zones=[],
            confidence_pct=90.0,
            observed_at=now - timedelta(hours=2),
            source_topic="frigate/events",
            raw={},
        )

        # Create a recent detection (30 minutes ago)
        recent_detection = FrigateDetection.objects.create(
            provider="frigate",
            event_id="recent-event",
            label="person",
            camera="frontyard",
            zones=[],
            confidence_pct=85.0,
            observed_at=now - timedelta(minutes=30),
            source_topic="frigate/events",
            raw={},
        )

        # Run cleanup
        deleted_count = cleanup_frigate_detections()

        # Old detection should be deleted
        self.assertEqual(deleted_count, 1)
        self.assertFalse(FrigateDetection.objects.filter(id=old_detection.id).exists())

        # Recent detection should remain
        self.assertTrue(FrigateDetection.objects.filter(id=recent_detection.id).exists())

    def test_cleanup_skips_when_disabled(self):
        """Cleanup should skip when Frigate is disabled."""
        self._set_frigate_settings(enabled=False, retention_seconds=3600)

        now = timezone.now()

        # Create an old detection
        FrigateDetection.objects.create(
            provider="frigate",
            event_id="old-event",
            label="person",
            camera="backyard",
            zones=[],
            confidence_pct=90.0,
            observed_at=now - timedelta(hours=2),
            source_topic="frigate/events",
            raw={},
        )

        # Run cleanup
        deleted_count = cleanup_frigate_detections()

        # Nothing should be deleted when disabled
        self.assertEqual(deleted_count, 0)
        self.assertEqual(FrigateDetection.objects.count(), 1)

    def test_cleanup_respects_retention_seconds(self):
        """Cleanup should use the configured retention_seconds."""
        self._set_frigate_settings(enabled=True, retention_seconds=86400)

        now = timezone.now()

        # Create a detection 2 hours ago (should NOT be deleted with 24h retention)
        detection = FrigateDetection.objects.create(
            provider="frigate",
            event_id="two-hours-old",
            label="person",
            camera="backyard",
            zones=[],
            confidence_pct=90.0,
            observed_at=now - timedelta(hours=2),
            source_topic="frigate/events",
            raw={},
        )

        # Run cleanup
        deleted_count = cleanup_frigate_detections()

        # Detection should NOT be deleted (2 hours < 24 hours)
        self.assertEqual(deleted_count, 0)
        self.assertTrue(FrigateDetection.objects.filter(id=detection.id).exists())

    def test_cleanup_deletes_multiple_old_detections(self):
        """Cleanup should delete all detections older than retention."""
        self._set_frigate_settings(enabled=True, retention_seconds=3600)

        now = timezone.now()

        # Create multiple old detections
        for i in range(5):
            FrigateDetection.objects.create(
                provider="frigate",
                event_id=f"old-event-{i}",
                label="person",
                camera="backyard",
                zones=[],
                confidence_pct=90.0,
                observed_at=now - timedelta(hours=2 + i),
                source_topic="frigate/events",
                raw={},
            )

        # Create one recent detection
        FrigateDetection.objects.create(
            provider="frigate",
            event_id="recent-event",
            label="person",
            camera="frontyard",
            zones=[],
            confidence_pct=85.0,
            observed_at=now - timedelta(minutes=30),
            source_topic="frigate/events",
            raw={},
        )

        # Run cleanup
        deleted_count = cleanup_frigate_detections()

        # All 5 old detections should be deleted
        self.assertEqual(deleted_count, 5)
        # Only the recent one should remain
        self.assertEqual(FrigateDetection.objects.count(), 1)
