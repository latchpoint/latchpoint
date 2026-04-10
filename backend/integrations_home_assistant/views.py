from __future__ import annotations

import logging

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
from alarm.integration_helpers import get_integration_enabled, set_integration_enabled
from config.domain_exceptions import ServiceUnavailableError, ValidationError

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
        """Return the current Home Assistant connection settings (env) + enabled state (DB)."""
        cfg = get_home_assistant_config()
        enabled = get_integration_enabled("home_assistant")
        return Response(
            {
                "enabled": enabled,
                "base_url": cfg["base_url"],
                "has_token": bool(cfg["token"]),
                "connect_timeout_seconds": cfg["connect_timeout_seconds"],
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        """Toggle Home Assistant enabled state (admin-only)."""
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValidationError("enabled (bool) is required.")
        set_integration_enabled("home_assistant", enabled)
        cfg = get_home_assistant_config()
        return Response(
            {
                "enabled": enabled,
                "base_url": cfg["base_url"],
                "has_token": bool(cfg["token"]),
                "connect_timeout_seconds": cfg["connect_timeout_seconds"],
            },
            status=status.HTTP_200_OK,
        )


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
