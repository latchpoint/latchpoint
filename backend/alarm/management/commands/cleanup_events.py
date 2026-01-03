"""Management command to manually run event cleanup."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from alarm.tasks import cleanup_old_events


class Command(BaseCommand):
    help = "Delete events older than the configured retention period"

    def handle(self, *args, **options):
        deleted = cleanup_old_events()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} old events"))
