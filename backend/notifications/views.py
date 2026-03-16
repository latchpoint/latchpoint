"""
API views for notification providers.
"""

import logging

from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.models import AlarmSettingsProfile
from config.domain_exceptions import ConfigurationError, NotFoundError, ServiceUnavailableError, ValidationError

logger = logging.getLogger(__name__)

from .dispatcher import get_dispatcher
from .handlers import get_all_handlers_metadata
from .handlers.home_assistant import HomeAssistantHandler
from .handlers.pushbullet import PushbulletHandler
from .models import NotificationLog, NotificationProvider
from .serializers import (
    HomeAssistantServiceSerializer,
    NotificationLogSerializer,
    NotificationProviderSerializer,
    ProviderTypeMetadataSerializer,
    PushbulletDeviceSerializer,
    PushbulletValidateTokenResultSerializer,
    TestNotificationResultSerializer,
)


def get_active_profile():
    """Get the active alarm settings profile."""
    return AlarmSettingsProfile.objects.filter(is_active=True).first()


class ProviderListCreateView(APIView):
    """List all providers or create a new one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List all notification providers for the active profile."""
        profile = get_active_profile()
        if not profile:
            return Response([])

        providers = NotificationProvider.objects.filter(profile=profile)
        serializer = NotificationProviderSerializer(providers, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Notification providers are now configured via environment variables."""
        raise MethodNotAllowed(request.method, detail="Notification providers are configured via environment variables.")


class ProviderDetailView(APIView):
    """Retrieve, update, or delete a notification provider."""

    permission_classes = [IsAuthenticated]

    def get_object(self, pk):
        """Get provider by ID."""
        profile = get_active_profile()
        if not profile:
            return None
        try:
            return NotificationProvider.objects.get(id=pk, profile=profile)
        except NotificationProvider.DoesNotExist:
            return None

    def get(self, request, pk):
        """Get a notification provider."""
        provider = self.get_object(pk)
        if not provider:
            raise NotFoundError("Provider not found.")

        serializer = NotificationProviderSerializer(provider)
        return Response(serializer.data)

    def put(self, request, pk):
        """Notification providers are now configured via environment variables."""
        raise MethodNotAllowed(request.method, detail="Notification providers are configured via environment variables.")

    patch = put

    def delete(self, request, pk):
        """Notification providers are now configured via environment variables."""
        raise MethodNotAllowed(request.method, detail="Notification providers are configured via environment variables.")


class TestProviderView(APIView):
    """Send a test notification to a provider."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """Send test notification."""
        profile = get_active_profile()
        if not profile:
            raise ValidationError("No active profile.")

        try:
            provider = NotificationProvider.objects.get(id=pk, profile=profile)
        except NotificationProvider.DoesNotExist:
            raise NotFoundError("Provider not found.")

        dispatcher = get_dispatcher()
        result = dispatcher.test_provider(provider)

        serializer = TestNotificationResultSerializer(
            {
                "success": result.success,
                "message": result.message,
                "error_code": result.error_code,
            }
        )
        return Response(serializer.data)


class TestHaSystemProviderView(APIView):
    """Test the Home Assistant system provider."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Test HA connectivity and list available notify services."""
        from integrations_home_assistant import api as ha_api

        # Check if HA is configured
        ha_status = ha_api.get_status()
        if not ha_status.configured:
            raise ServiceUnavailableError("Home Assistant is not configured.")

        if not ha_status.reachable:
            raise ServiceUnavailableError("Home Assistant is not reachable.")

        # Get available notify services for info
        services = ha_api.list_notify_services()
        service_count = len(services)

        return Response(
            {
                "success": True,
                "message": f"Home Assistant connected. {service_count} notify service(s) available.",
                "error_code": None,
            }
        )


class ProviderTypesView(APIView):
    """List available provider types with their schemas."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all available provider types and their metadata."""
        metadata = get_all_handlers_metadata()
        serializer = ProviderTypeMetadataSerializer(metadata, many=True)
        return Response(serializer.data)


class NotificationLogListView(APIView):
    """List notification logs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get recent notification logs."""
        profile = get_active_profile()
        if not profile:
            return Response([])

        # Get logs for providers in this profile
        provider_ids = NotificationProvider.objects.filter(profile=profile).values_list(
            "id", flat=True
        )

        logs = NotificationLog.objects.filter(provider_id__in=provider_ids).order_by(
            "-created_at"
        )[:100]

        serializer = NotificationLogSerializer(logs, many=True)
        return Response(serializer.data)


# Provider-specific endpoints


class PushbulletDevicesView(APIView):
    """List Pushbullet devices for a token."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        List devices for the Pushbullet account configured via env vars.

        The access token is always read from the PUSHBULLET_ACCESS_TOKEN
        environment variable.
        """
        env_config = PushbulletHandler.from_env()
        access_token = env_config.get("access_token")

        if not access_token:
            raise ConfigurationError("Pushbullet access token not configured in environment.")

        handler = PushbulletHandler()
        devices = handler.list_devices(access_token)

        serializer = PushbulletDeviceSerializer(devices, many=True)
        return Response({"devices": serializer.data})


class PushbulletValidateTokenView(APIView):
    """Validate the env-configured Pushbullet access token."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Validate the env-configured Pushbullet access token."""
        env_config = PushbulletHandler.from_env()
        access_token = env_config.get("access_token")
        if not access_token:
            raise ConfigurationError("Pushbullet access token not configured in environment.")

        handler = PushbulletHandler()
        user_info = handler.get_user_info(access_token)

        if user_info:
            result = {
                "valid": True,
                "user": {
                    "name": user_info.get("name"),
                    "email": user_info.get("email_normalized"),
                },
            }
        else:
            result = {
                "valid": False,
                "error": "Invalid access token",
            }

        return Response(PushbulletValidateTokenResultSerializer(result).data)


class HomeAssistantServicesView(APIView):
    """List Home Assistant notify services."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get available Home Assistant notify services."""
        services = HomeAssistantHandler.list_available_services()
        data = [{"service": s} for s in services]
        serializer = HomeAssistantServiceSerializer(data, many=True)
        return Response({"services": serializer.data})
