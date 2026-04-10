from __future__ import annotations

import logging
import sys
import warnings

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class IntegrationsZwavejsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_zwavejs"

    def ready(self) -> None:
        """Best-effort runtime hooks for Z-Wave JS integration."""
        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.env_config import get_zwavejs_config
            from alarm.gateways.zwavejs import default_zwavejs_gateway
            from alarm.signals import settings_profile_changed
        except Exception:
            return

        def _apply_zwavejs_settings() -> None:
            """Apply Z-Wave JS settings from env vars + DB overrides to the runtime gateway."""
            try:
                from alarm.state_machine.settings import get_setting_json
                from alarm.use_cases.settings_profile import ensure_active_settings_profile

                cfg = get_zwavejs_config()
                profile = ensure_active_settings_profile()
                db = get_setting_json(profile, "zwavejs") or {}
                if not isinstance(db, dict):
                    db = {}
                cfg["enabled"] = bool(db.get("enabled", False))
                cfg["connect_timeout_seconds"] = int(db.get("connect_timeout_seconds", cfg["connect_timeout_seconds"]))
                cfg["reconnect_min_seconds"] = int(db.get("reconnect_min_seconds", cfg["reconnect_min_seconds"]))
                cfg["reconnect_max_seconds"] = int(db.get("reconnect_max_seconds", cfg["reconnect_max_seconds"]))
                default_zwavejs_gateway.apply_settings(settings_obj=cfg)
            except Exception:
                return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Re-apply Z-Wave JS settings when profile changes (e.g. enabled toggled)."""
            _apply_zwavejs_settings()

        settings_profile_changed.connect(
            _on_settings_profile_changed,
            dispatch_uid="zwavejs_profile_changed",
        )

        # Apply settings once at process startup.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Accessing the database during app initialization")
            _apply_zwavejs_settings()
