from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Notification Providers"

    def ready(self) -> None:
        # Import tasks to register them with the scheduler
        from . import tasks  # noqa: F401
