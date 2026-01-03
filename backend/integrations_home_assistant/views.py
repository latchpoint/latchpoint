from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db import transaction

from accounts.permissions import IsAdminRole
from config.domain_exceptions import ConfigurationError, ServiceUnavailableError, ValidationError
from alarm.gateways.home_assistant import (
    HomeAssistantGateway,
    default_home_assistant_gateway,
)
from alarm.models import AlarmSettingsEntry
from alarm.serializers import (
    HomeAssistantConnectionSettingsSerializer,
    HomeAssistantConnectionSettingsUpdateSerializer,
)
from alarm.crypto import can_encrypt, encrypt_secret
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from alarm.signals import settings_profile_changed
from integrations_home_assistant.config import normalize_home_assistant_connection
from integrations_home_assistant.connection import set_cached_connection

ha_gateway: HomeAssistantGateway = default_home_assistant_gateway
logger = logging.getLogger(__name__)


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
        """Return the current persisted Home Assistant connection settings."""
        profile = ensure_active_settings_profile()
        value = normalize_home_assistant_connection(get_setting_json(profile, "home_assistant_connection") or {})
        return Response(HomeAssistantConnectionSettingsSerializer(value).data, status=status.HTTP_200_OK)

    def patch(self, request):
        """Update persisted Home Assistant settings and refresh runtime cache (admin-only)."""
        profile = ensure_active_settings_profile()
        current = normalize_home_assistant_connection(get_setting_json(profile, "home_assistant_connection") or {})

        serializer = HomeAssistantConnectionSettingsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)

        if "token" in changes:
            token = changes.get("token") or ""
            if token != "" and not can_encrypt():
                raise ConfigurationError("SETTINGS_ENCRYPTION_KEY is required to store the Home Assistant token.")
            changes["token"] = encrypt_secret(token)
        else:
            # Preserve existing token if not provided.
            changes["token"] = current.get("token", "")

        merged = dict(current)
        merged.update(changes)
        merged = normalize_home_assistant_connection(merged)

        if merged.get("enabled"):
            if not str(merged.get("base_url") or "").strip():
                raise ValidationError("Home Assistant base_url is required when enabled.")
            if not str(merged.get("token") or "").strip():
                raise ValidationError("Home Assistant token is required when enabled.")

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["home_assistant_connection"]
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="home_assistant_connection",
            defaults={"value": merged, "value_type": definition.value_type},
        )

        # Best-effort: refresh runtime cache so other requests don't need DB reads.
        try:
            set_cached_connection(merged)
        except Exception:
            pass

        transaction.on_commit(lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated"))
        return Response(HomeAssistantConnectionSettingsSerializer(merged).data, status=status.HTTP_200_OK)


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
