from __future__ import annotations

from rest_framework import serializers


class ZwavejsConnectionSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    ws_url = serializers.CharField(required=False, allow_blank=True)
    has_api_token = serializers.BooleanField(required=False)
    connect_timeout_seconds = serializers.FloatField(required=False)
    reconnect_min_seconds = serializers.IntegerField(required=False)
    reconnect_max_seconds = serializers.IntegerField(required=False)


class ZwavejsTestConnectionSerializer(serializers.Serializer):
    ws_url = serializers.CharField()
    api_token = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    connect_timeout_seconds = serializers.FloatField(required=False)


class ZwavejsSetValueSerializer(serializers.Serializer):
    node_id = serializers.IntegerField(min_value=1)
    command_class = serializers.IntegerField(min_value=1)
    endpoint = serializers.IntegerField(required=False, min_value=0, default=0)
    property = serializers.JSONField()
    property_key = serializers.JSONField(required=False, allow_null=True)
    value = serializers.JSONField()

    def validate_property(self, value):
        """Validate that the value-id property is a string or integer."""
        if isinstance(value, (str, int)):
            return value
        raise serializers.ValidationError("property must be a string or number.")

    def validate_property_key(self, value):
        """Validate that the value-id property_key is a string/integer or null."""
        if value is None:
            return None
        if isinstance(value, (str, int)):
            return value
        raise serializers.ValidationError("property_key must be a string, number, or null.")
