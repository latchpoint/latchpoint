from __future__ import annotations

from django.apps import AppConfig


class LocksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "locks"
    verbose_name = "Door Locks"

    def ready(self) -> None:
        # Import tasks to register them with the scheduler
        from . import tasks  # noqa: F401
