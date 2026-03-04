"""
Serializers for notification providers API.
"""

from rest_framework import serializers

from .handlers import get_handler
from .models import NotificationLog, NotificationProvider


class NotificationProviderSerializer(serializers.ModelSerializer):
    """Serializer for NotificationProvider model (read-only)."""

    provider_type_display = serializers.CharField(
        source="get_provider_type_display", read_only=True
    )

    class Meta:
        model = NotificationProvider
        fields = [
            "id",
            "name",
            "provider_type",
            "provider_type_display",
            "config",
            "is_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class NotificationLogSerializer(serializers.ModelSerializer):
    """Serializer for NotificationLog model."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = NotificationLog
        fields = [
            "id",
            "provider_name",
            "provider_type",
            "status",
            "status_display",
            "message_preview",
            "error_message",
            "error_code",
            "rule_name",
            "created_at",
        ]
        read_only_fields = fields


class ProviderTypeMetadataSerializer(serializers.Serializer):
    """Serializer for provider type metadata."""

    provider_type = serializers.CharField()
    display_name = serializers.CharField()
    config_schema = serializers.JSONField()


class TestNotificationResultSerializer(serializers.Serializer):
    """Serializer for test notification result."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    error_code = serializers.CharField(allow_null=True, required=False)


class PushbulletDeviceSerializer(serializers.Serializer):
    """Serializer for Pushbullet device info."""

    iden = serializers.CharField()
    nickname = serializers.CharField()
    model = serializers.CharField(allow_null=True, required=False)
    type = serializers.CharField(allow_null=True, required=False)
    pushable = serializers.BooleanField()


class PushbulletValidateTokenSerializer(serializers.Serializer):
    """Serializer for Pushbullet token validation request."""

    access_token = serializers.CharField()


class PushbulletValidateTokenResultSerializer(serializers.Serializer):
    """Serializer for Pushbullet token validation result."""

    valid = serializers.BooleanField()
    error = serializers.CharField(required=False)
    user = serializers.DictField(required=False)


class HomeAssistantServiceSerializer(serializers.Serializer):
    """Serializer for HA notify service."""

    service = serializers.CharField()
