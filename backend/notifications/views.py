"""
API views for notification providers.
"""

import logging

from django.db import IntegrityError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.models import AlarmSettingsProfile
from config.domain_exceptions import ConfigurationError, NotFoundError, ServiceUnavailableError, ValidationError

from .dispatcher import get_dispatcher
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
    TestNotificationResultSerializer,
)

logger = logging.getLogger(__name__)


def get_active_profile():
    """Get the active alarm settings profile."""
    return AlarmSettingsProfile.objects.filter(is_active=True).first()


class ProviderListCreateView(APIView):
    """List all providers or create a new one."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated()]

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

        data = request.data
        if not isinstance(data, dict):
            raise ValidationError("Request body must be an object.")

        provider_type = data.get("provider_type", "")
        name = data.get("name", "")
        config = data.get("config", {})
        if not isinstance(config, dict):
            raise ValidationError("config must be an object.")
        is_enabled = data.get("is_enabled", True)

        if not provider_type or not name:
            raise ValidationError("provider_type and name are required.")

        # Validate provider type exists
        try:
            handler = get_handler(provider_type)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        # Validate config against handler
        config_errors = handler.validate_config(config)
        if config_errors:
            raise ValidationError({"config": config_errors})

        provider = NotificationProvider(
            profile=profile,
            name=name,
            provider_type=provider_type,
            is_enabled=is_enabled,
        )
        try:
            provider.set_config_with_encryption(config, partial=False)
        except IntegrityError as exc:
            raise ValidationError(f"A notification provider named '{name}' already exists.") from exc
        serializer = NotificationProviderSerializer(provider)
        return Response(serializer.data, status=201)


class ProviderDetailView(APIView):
    """Retrieve, update, or delete a notification provider."""

    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated()]

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

    def patch(self, request, pk):
        """Update a notification provider."""
        provider = self.get_object(pk)
        if not provider:
            raise NotFoundError("Provider not found.")

        data = request.data
        if not isinstance(data, dict):
            raise ValidationError("Request body must be an object.")

        update_fields = ["updated_at"]
        if "name" in data:
            provider.name = data["name"]
            update_fields.append("name")
        if "is_enabled" in data:
            provider.is_enabled = data["is_enabled"]
            update_fields.append("is_enabled")
        if "config" in data:
            if not isinstance(data["config"], dict):
                raise ValidationError("config must be an object.")
            # Validate config against handler
            handler = get_handler(provider.provider_type)
            # Build the merged config for validation (mirrors set_config_with_encryption partial merge)
            merged = {**(provider.get_decrypted_config() or {}), **data["config"]}
            config_errors = handler.validate_config(merged)
            if config_errors:
                raise ValidationError({"config": config_errors})
            provider.set_config_with_encryption(data["config"], save=False)
            update_fields.append("config")
        try:
            provider.save(update_fields=update_fields)
        except IntegrityError as exc:
            raise ValidationError(f"A notification provider named '{provider.name}' already exists.") from exc

        serializer = NotificationProviderSerializer(provider)
        return Response(serializer.data)

    def delete(self, request, pk):
        """Delete a notification provider."""
        provider = self.get_object(pk)
        if not provider:
            raise NotFoundError("Provider not found.")

        provider.delete()
        return Response(status=204)


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
        except NotificationProvider.DoesNotExist as exc:
            raise NotFoundError("Provider not found.") from exc

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
        provider_ids = NotificationProvider.objects.filter(profile=profile).values_list("id", flat=True)

        logs = NotificationLog.objects.filter(provider_id__in=provider_ids).order_by("-created_at")[:100]

        serializer = NotificationLogSerializer(logs, many=True)
        return Response(serializer.data)


# Provider-specific endpoints


class PushbulletDevicesView(APIView):
    """List Pushbullet devices for the configured provider."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List devices for a Pushbullet provider from DB config."""
        profile = get_active_profile()
        if not profile:
            raise ConfigurationError("No active profile.")

        provider_id = request.query_params.get("provider_id")
        if provider_id:
            try:
                provider = NotificationProvider.objects.get(id=provider_id, profile=profile, provider_type="pushbullet")
            except NotificationProvider.DoesNotExist:
                raise NotFoundError("Pushbullet provider not found.") from None
        else:
            provider = NotificationProvider.objects.filter(
                profile=profile, provider_type="pushbullet", is_enabled=True
            ).first()
        if not provider:
            raise ConfigurationError("No enabled Pushbullet provider configured.")

        config = provider.get_decrypted_config()
        access_token = config.get("access_token")
        if not access_token:
            raise ConfigurationError("Pushbullet access token not configured.")

        handler = PushbulletHandler()
        devices = handler.list_devices(access_token)

        serializer = PushbulletDeviceSerializer(devices, many=True)
        return Response({"devices": serializer.data})


class PushbulletValidateTokenView(APIView):
    """Validate a Pushbullet access token from the configured provider."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Validate the Pushbullet access token for a provider."""
        profile = get_active_profile()
        if not profile:
            raise ConfigurationError("No active profile.")

        provider_id = request.data.get("provider_id") if isinstance(request.data, dict) else None
        if provider_id:
            try:
                provider = NotificationProvider.objects.get(id=provider_id, profile=profile, provider_type="pushbullet")
            except NotificationProvider.DoesNotExist:
                raise NotFoundError("Pushbullet provider not found.") from None
        else:
            provider = NotificationProvider.objects.filter(
                profile=profile, provider_type="pushbullet", is_enabled=True
            ).first()
        if not provider:
            raise ConfigurationError("No enabled Pushbullet provider configured.")

        config = provider.get_decrypted_config()
        access_token = config.get("access_token")
        if not access_token:
            raise ConfigurationError("Pushbullet access token not configured.")

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
