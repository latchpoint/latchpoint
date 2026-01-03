from __future__ import annotations

from django.core.management.base import BaseCommand

from alarm import rules_engine


class Command(BaseCommand):
    help = "Evaluate and execute enabled alarm rules."

    def handle(self, *args, **options):
        """Run rules engine and print a summary."""
        result = rules_engine.run_rules(actor_user=None)
        self.stdout.write(self.style.SUCCESS(f"Rules run: {result.as_dict()}"))
