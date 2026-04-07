from __future__ import annotations

from django.apps import AppConfig


class AlarmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "alarm"

    def ready(self) -> None:
        """Wire websocket/system-status hooks for the alarm app at startup."""
        # Keep `alarm` core free of integration initialization; integrations bind via `alarm.signals`.
        # Core realtime updates are wired here to avoid import side effects at module load time.
        # Configure the in-memory log viewer buffer (ADR 0072)
        import logging

        from django.conf import settings

        # Import tasks to register them with the scheduler
        from . import (
            log_handler,
            receivers,  # noqa: F401
            system_status,  # noqa: F401
            tasks,  # noqa: F401
            ws_signals,  # noqa: F401
        )

        log_handler.configure(
            buffer_size=settings.LOG_VIEWER_BUFFER_SIZE,
            capture_level=getattr(logging, settings.LOG_VIEWER_CAPTURE_LEVEL, logging.DEBUG),
            broadcast_level=getattr(logging, settings.LOG_VIEWER_BROADCAST_LEVEL, logging.WARNING),
        )
