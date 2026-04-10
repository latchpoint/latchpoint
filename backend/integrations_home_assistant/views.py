from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.env_config import get_home_assistant_config
from alarm.gateways.home_assistant import (
    HomeAssistantGateway,
    default_home_assistant_gateway,
)
from alarm.models import AlarmSettingsEntry
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.signals import settings_profile_changed
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from config.domain_exceptions import ServiceUnavailableError, ValidationError
from integrations_home_assistant.connection import set_cached_connection

ha_gateway: HomeAssistantGateway = default_home_assistant_gateway
logger = logging.getLogger(__name__)


def _get_ha_settings() -> dict:
    """Return merged HA settings: env connection config + DB operational overrides."""
    cfg = get_home_assistant_config()
    profile = ensure_active_settings_profile()
    db_settings = get_setting_json(profile, "home_assistant") or {}
    if not isinstance(db_settings, dict):
        db_settings = {}
    return {
        "enabled": cfg["enabled"],
        "base_url": cfg["base_url"],
        "token": cfg["token"],
        "connect_timeout_seconds": int(
            db_settings.get("connect_timeout_seconds", cfg["connect_timeout_seconds"])
        ),
    }


def _ha_response(settings: dict) -> dict:
    """Build the API response dict (masks token)."""
    return {
        "enabled": settings["enabled"],
        "base_url": settings["base_url"],
        "has_token": bool(settings.get("token")),
        "connect_timeout_seconds": settings["connect_timeout_seconds"],
    }


class _HomeAssistantBaseView(APIView):
    def get_gateway(self) -> HomeAssistantGateway:
        """Return the Home Assistant gateway used by this view."""
        return ha_gateway


class HomeAssistantStatusView(_HomeAssistantBaseView):
    def get(self, request):
        """Return Home Assistant connection status."""
        status_obj = self.get_gateway().get_status()
        return Response(status_obj.as_dict(), status=status.HTTP_200_OK)


class HomeAssistantSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current Home Assistant connection settings (env) + operational settings (DB)."""
        settings = _get_ha_settings()
        return Response(_ha_response(settings), status=status.HTTP_200_OK)

    def patch(self, request):
        """Update Home Assistant operational settings (admin-only)."""
        data = request.data
        if not isinstance(data, dict) or not data:
            raise ValidationError("Request body must be a non-empty object.")

        profile = ensure_active_settings_profile()
        current = get_setting_json(profile, "home_assistant") or {}
        if not isinstance(current, dict):
            current = {}

        if "connect_timeout_seconds" in data:
            val = data["connect_timeout_seconds"]
            if not isinstance(val, int) or val < 1 or val > 300:
                raise ValidationError("connect_timeout_seconds must be an integer between 1 and 300.")
            current["connect_timeout_seconds"] = val

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["home_assistant"]
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="home_assistant",
            defaults={"value": current, "value_type": definition.value_type},
        )

        set_cached_connection()
        settings = _get_ha_settings()
        transaction.on_commit(
            lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated")
        )
        return Response(_ha_response(settings), status=status.HTTP_200_OK)


class HomeAssistantEntitiesView(_HomeAssistantBaseView):
    def get(self, request):
        """List entities from Home Assistant (requires configured/reachable connection)."""
        gateway = self.get_gateway()
        gateway.ensure_available()
        try:
            entities = gateway.list_entities()
        except Exception as exc:
            logger.exception("Failed to fetch Home Assistant entities")
            raise ServiceUnavailableError("Failed to fetch Home Assistant entities.") from exc
        return Response({"data": entities}, status=status.HTTP_200_OK)


class HomeAssistantNotifyServicesView(_HomeAssistantBaseView):
    def get(self, request):
        """List notify service names from Home Assistant (requires configured/reachable connection)."""
        gateway = self.get_gateway()
        gateway.ensure_available()
        try:
            services = gateway.list_notify_services()
        except Exception as exc:
            logger.exception("Failed to fetch Home Assistant notify services")
            raise ServiceUnavailableError("Failed to fetch Home Assistant notify services.") from exc
        return Response({"data": services}, status=status.HTTP_200_OK)
