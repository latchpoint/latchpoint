from __future__ import annotations

from django.apps import AppConfig


class AlarmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alarm"

    def ready(self) -> None:
        """Wire websocket/system-status hooks for the alarm app at startup."""
        # Keep `alarm` core free of integration initialization; integrations bind via `alarm.signals`.
        # Core realtime updates are wired here to avoid import side effects at module load time.
        from . import ws_signals  # noqa: F401
        from . import receivers  # noqa: F401
        from . import system_status  # noqa: F401

        # Import tasks to register them with the scheduler
        from . import tasks  # noqa: F401

        # Configure the in-memory log viewer buffer (ADR 0072)
        import logging

        from django.conf import settings

        from . import log_handler

        log_handler.configure(
            buffer_size=settings.LOG_VIEWER_BUFFER_SIZE,
            capture_level=getattr(logging, settings.LOG_VIEWER_CAPTURE_LEVEL, logging.DEBUG),
            broadcast_level=getattr(logging, settings.LOG_VIEWER_BROADCAST_LEVEL, logging.WARNING),
        )
