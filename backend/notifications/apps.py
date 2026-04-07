import logging
import sys
import warnings

from django.apps import AppConfig
from django.db import DatabaseError, OperationalError

logger = logging.getLogger(__name__)


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notifications"
    verbose_name = "Notification Providers"

    def ready(self) -> None:
        # Import tasks to register them with the scheduler
        from . import tasks  # noqa: F401

        # Auto-provision env-based notification providers (skip management commands).
        subcommand = sys.argv[1] if len(sys.argv) > 1 else ""
        if subcommand in {"makemigrations", "migrate", "collectstatic", "test"}:
            return
        if "pytest" in sys.argv[0]:
            return

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            try:
                from alarm.models import AlarmSettingsProfile

                from .provider_registry import ensure_env_providers_exist

                profile = AlarmSettingsProfile.objects.filter(is_active=True).first()
                if profile:
                    ensure_env_providers_exist(profile)
            except (DatabaseError, OperationalError):
                logger.warning("Notification provider auto-provisioning failed", exc_info=True)
