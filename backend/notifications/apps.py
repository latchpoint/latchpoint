from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Notification Providers"

    def ready(self) -> None:
        # Register scheduler tasks and wire signal receivers (ADR-0098)
        from . import receivers, tasks  # noqa: F401
