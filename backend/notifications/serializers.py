"""
Serializers for notification providers API.
"""

from rest_framework import serializers

from alarm.crypto import EncryptionNotConfigured

from .encryption import encrypt_config, mask_config
from .handlers import get_all_handlers_metadata, get_handler
from .models import NotificationLog, NotificationProvider


class NotificationProviderSerializer(serializers.ModelSerializer):
    """Serializer for NotificationProvider model."""

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
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_representation(self, instance):
        """Mask sensitive fields in config for API responses."""
        data = super().to_representation(instance)

        # Get handler to know which fields to mask
        try:
            handler = get_handler(instance.provider_type)
            data["config"] = mask_config(instance.config, handler.encrypted_fields)
        except ValueError:
            # Unknown provider type - return config as-is (shouldn't happen)
            pass

        return data

    def validate_provider_type(self, value):
        """Validate that provider type is supported."""
        try:
            get_handler(value)
        except ValueError:
            raise serializers.ValidationError(f"Unknown provider type: {value}")
        return value

    def validate(self, attrs):
        """Validate the provider configuration."""
        # Only validate config if it's being created or config is being updated
        if "config" not in attrs and self.instance:
            # Partial update without config change - skip config validation
            return attrs

        provider_type = attrs.get("provider_type") or (
            self.instance.provider_type if self.instance else None
        )
        config = attrs.get("config", {})

        if provider_type and config:
            try:
                handler = get_handler(provider_type)
                errors = handler.validate_config(config)
                if errors:
                    raise serializers.ValidationError({"config": errors})
            except ValueError:
                pass  # Already validated in validate_provider_type

        return attrs

    def create(self, validated_data):
        """Create provider with encrypted config."""
        provider_type = validated_data.get("provider_type")
        config = validated_data.get("config", {})

        # Encrypt sensitive fields
        try:
            handler = get_handler(provider_type)
            validated_data["config"] = encrypt_config(config, handler.encrypted_fields)
        except ValueError:
            pass
        except EncryptionNotConfigured as e:
            raise serializers.ValidationError(
                {"config": [f"Encryption error: {e}. Please configure SETTINGS_ENCRYPTION_KEY."]}
            )

        # Add profile from context
        validated_data["profile"] = self.context["profile"]

        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Update provider with encrypted config."""
        if "config" in validated_data:
            config = validated_data["config"]
            provider_type = validated_data.get("provider_type", instance.provider_type)

            try:
                handler = get_handler(provider_type)

                # Merge with existing config for partial updates
                # If a secret field is not provided, keep the existing encrypted value
                existing_config = instance.config or {}
                for field in handler.encrypted_fields:
                    if field not in config or not config[field]:
                        # Keep existing encrypted value
                        if field in existing_config:
                            config[field] = existing_config[field]

                validated_data["config"] = encrypt_config(
                    config, handler.encrypted_fields
                )
            except ValueError:
                pass
            except EncryptionNotConfigured as e:
                raise serializers.ValidationError(
                    {"config": [f"Encryption error: {e}. Please configure SETTINGS_ENCRYPTION_KEY."]}
                )

        return super().update(instance, validated_data)


class NotificationProviderCreateSerializer(NotificationProviderSerializer):
    """Serializer for creating notification providers."""

    class Meta(NotificationProviderSerializer.Meta):
        fields = NotificationProviderSerializer.Meta.fields


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
    encrypted_fields = serializers.ListField(child=serializers.CharField())
    config_schema = serializers.JSONField()


class TestNotificationSerializer(serializers.Serializer):
    """Serializer for test notification request."""

    pass  # No input needed for test


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
