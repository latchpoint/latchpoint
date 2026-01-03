from __future__ import annotations

from rest_framework import serializers

from integrations_home_assistant.config import (
    mask_home_assistant_connection,
    normalize_home_assistant_connection,
)


class HomeAssistantConnectionSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    base_url = serializers.CharField(required=False, allow_blank=True)
    connect_timeout_seconds = serializers.FloatField(required=False)
    has_token = serializers.BooleanField(required=False)

    def to_representation(self, instance: object):
        """Return a masked representation of the stored connection settings."""
        return mask_home_assistant_connection(instance)


class HomeAssistantConnectionSettingsUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    base_url = serializers.CharField(required=False, allow_blank=True)
    token = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    connect_timeout_seconds = serializers.FloatField(required=False)

    def validate(self, attrs):
        """Validate timeout after normalizing inputs."""
        normalized = normalize_home_assistant_connection(attrs)
        timeout = normalized.get("connect_timeout_seconds")
        if timeout is not None and float(timeout) <= 0:
            raise serializers.ValidationError("connect_timeout_seconds must be > 0.")
        return attrs
