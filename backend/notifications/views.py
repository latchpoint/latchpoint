"""
API views for notification providers.
"""

import logging

from django.db.utils import IntegrityError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError as DrfValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.models import AlarmSettingsProfile
from config.domain_exceptions import ConfigurationError, NotFoundError, ServiceUnavailableError, ValidationError

logger = logging.getLogger(__name__)

from .dispatcher import get_dispatcher
from .encryption import decrypt_config
from .handlers import get_all_handlers_metadata, get_handler
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
    PushbulletValidateTokenSerializer,
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
        """Create a new notification provider."""
        profile = get_active_profile()
        if not profile:
            raise ValidationError("No active profile.")

        serializer = NotificationProviderSerializer(
            data=request.data,
            context={"profile": profile, "request": request},
        )
        serializer.is_valid(raise_exception=True)
        try:
            provider = serializer.save()
        except IntegrityError:
            raise DrfValidationError({"name": ["A provider with this name already exists."]})
        return Response(
            NotificationProviderSerializer(provider).data,
            status=status.HTTP_201_CREATED,
        )


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
        """Update a notification provider."""
        provider = self.get_object(pk)
        if not provider:
            raise NotFoundError("Provider not found.")

        serializer = NotificationProviderSerializer(
            provider,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        try:
            provider = serializer.save()
        except IntegrityError:
            raise DrfValidationError({"name": ["A provider with this name already exists."]})
        return Response(NotificationProviderSerializer(provider).data)

    # PATCH uses the same logic as PUT (both support partial updates)
    patch = put

    def delete(self, request, pk):
        """Delete a notification provider."""
        provider = self.get_object(pk)
        if not provider:
            raise NotFoundError("Provider not found.")

        provider.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        List devices for a Pushbullet account.

        Query params:
            - access_token: Direct token (for new provider setup)
            - provider_id: Use token from existing provider
        """
        from alarm.crypto import EncryptionNotConfigured

        access_token = request.query_params.get("access_token")
        provider_id = request.query_params.get("provider_id")

        if provider_id:
            try:
                provider = NotificationProvider.objects.get(id=provider_id)
                handler = get_handler(provider.provider_type)
                config = decrypt_config(provider.config, handler.encrypted_fields)
                access_token = config.get("access_token")
            except NotificationProvider.DoesNotExist:
                raise NotFoundError("Provider not found.")
            except EncryptionNotConfigured as exc:
                raise ConfigurationError(str(exc)) from exc
            except Exception as exc:
                logger.exception("Error retrieving provider config")
                raise ServiceUnavailableError("Failed to retrieve provider config.") from exc

        if not access_token:
            raise ValidationError("Access token required.")

        handler = PushbulletHandler()
        devices = handler.list_devices(access_token)

        serializer = PushbulletDeviceSerializer(devices, many=True)
        return Response({"devices": serializer.data})


class PushbulletValidateTokenView(APIView):
    """Validate a Pushbullet access token."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Validate a Pushbullet access token."""
        serializer = PushbulletValidateTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        access_token = serializer.validated_data["access_token"]
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
