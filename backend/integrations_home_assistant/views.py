from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.gateways.home_assistant import (
    HomeAssistantGateway,
    default_home_assistant_gateway,
)
from alarm.models import AlarmSettingsEntry
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.signals import settings_profile_changed
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from config.domain_exceptions import ServiceUnavailableError, ValidationError
from integrations_home_assistant.connection import set_cached_connection

ha_gateway: HomeAssistantGateway = default_home_assistant_gateway
logger = logging.getLogger(__name__)


def _get_entry(profile=None) -> AlarmSettingsEntry:
    """Return (or create) the home_assistant AlarmSettingsEntry for the active profile."""
    if profile is None:
        profile = ensure_active_settings_profile()
    definition = ALARM_PROFILE_SETTINGS_BY_KEY["home_assistant"]
    entry, _ = AlarmSettingsEntry.objects.get_or_create(
        profile=profile,
        key="home_assistant",
        defaults={"value": definition.default, "value_type": definition.value_type},
    )
    return entry


def get_ha_settings() -> dict:
    """Return decrypted HA settings for runtime consumers (gateways, commands)."""
    return _get_entry().get_decrypted_value()


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
        """Return Home Assistant settings with secrets masked."""
        entry = _get_entry()
        return Response(entry.get_masked_value_with_defaults(), status=status.HTTP_200_OK)

    def patch(self, request):
        """Update Home Assistant settings (connection + operational)."""
        data = request.data
        if not isinstance(data, dict) or not data:
            raise ValidationError("Request body must be a non-empty object.")

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["home_assistant"]
        allowed = set(definition.config_schema["properties"])
        invalid = set(data) - allowed
        if invalid:
            raise ValidationError(f"Unknown fields: {', '.join(sorted(invalid))}")

        profile = ensure_active_settings_profile()
        entry = _get_entry(profile)
        entry.set_value_with_encryption(data)

        set_cached_connection()
        transaction.on_commit(
            lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated")
        )
        return Response(entry.get_masked_value_with_defaults(), status=status.HTTP_200_OK)


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
