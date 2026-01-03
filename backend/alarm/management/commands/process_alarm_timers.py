from __future__ import annotations

from django.core.management.base import BaseCommand

from alarm.use_cases.process_timers import tick_alarm_timers


class Command(BaseCommand):
    help = "Process alarm timer expirations."

    def handle(self, *args, **options):
        """Process any due alarm timers and print the resulting state."""
        result = tick_alarm_timers()
        self.stdout.write(f"alarm_state={result.state}")
