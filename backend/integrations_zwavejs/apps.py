from __future__ import annotations

import sys

from django.apps import AppConfig


class IntegrationsZwavejsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations_zwavejs"

    def ready(self) -> None:
        """Register setting maskers and best-effort runtime hooks for Z-Wave JS integration."""
        try:
            from alarm.integration_settings_masking import register_setting_masker
            from integrations_zwavejs.config import mask_zwavejs_connection

            register_setting_masker(key="zwavejs_connection", masker=mask_zwavejs_connection)
        except Exception:
            return

        argv = " ".join(sys.argv).lower()
        if any(token in argv for token in ["makemigrations", "migrate", "collectstatic", "pytest", " test"]):
            return

        try:
            from alarm.gateways.zwavejs import default_zwavejs_gateway
            from alarm.signals import settings_profile_changed
            from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
            from integrations_zwavejs.config import normalize_zwavejs_connection, prepare_runtime_zwavejs_connection
        except Exception:
            return

        def _apply_from_active_profile() -> None:
            """Apply Z-Wave JS settings from the active profile to the runtime gateway (best-effort)."""
            try:
                profile = get_active_settings_profile()
                settings_obj = normalize_zwavejs_connection(get_setting_json(profile, "zwavejs_connection") or {})
                default_zwavejs_gateway.apply_settings(settings_obj=prepare_runtime_zwavejs_connection(settings_obj))
            except Exception:
                return

        def _on_settings_profile_changed(sender, *, profile_id: int, reason: str, **_kwargs) -> None:
            """Refresh runtime Z-Wave JS settings when the profile changes."""
            _apply_from_active_profile()

        settings_profile_changed.connect(_on_settings_profile_changed, dispatch_uid="zwavejs_profile_changed")

        # Apply settings once at process startup so the runtime connection manager is configured
        # even if no HTTP status endpoint is hit (e.g. clients rely on websocket snapshots).
        _apply_from_active_profile()
