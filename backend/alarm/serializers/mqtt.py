from __future__ import annotations

from rest_framework import serializers

from transports_mqtt.config import mask_mqtt_connection, normalize_mqtt_connection


class MqttConnectionSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    host = serializers.CharField(allow_blank=True)
    port = serializers.IntegerField()
    username = serializers.CharField(allow_blank=True)
    use_tls = serializers.BooleanField()
    tls_insecure = serializers.BooleanField()
    client_id = serializers.CharField(allow_blank=True)
    keepalive_seconds = serializers.IntegerField()
    connect_timeout_seconds = serializers.FloatField()
    has_password = serializers.BooleanField(read_only=True)

    def to_representation(self, instance):
        """Return a masked representation of the stored connection settings."""
        return mask_mqtt_connection(instance)


class MqttConnectionSettingsUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    host = serializers.CharField(required=False, allow_blank=True)
    port = serializers.IntegerField(required=False, min_value=1, max_value=65535)
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True)
    use_tls = serializers.BooleanField(required=False)
    tls_insecure = serializers.BooleanField(required=False)
    client_id = serializers.CharField(required=False, allow_blank=True)
    keepalive_seconds = serializers.IntegerField(required=False, min_value=5, max_value=3600)
    connect_timeout_seconds = serializers.FloatField(required=False, min_value=0.5, max_value=30)

    def validate(self, attrs):
        """Validate conditional requirements when enabling MQTT."""
        # Only enforce required host/port when explicitly enabling.
        enabled = attrs.get("enabled")
        host = attrs.get("host")
        if enabled is True and (host is None or host.strip() == ""):
            raise serializers.ValidationError({"host": "Host is required when MQTT is enabled."})
        return attrs


class MqttTestConnectionSerializer(serializers.Serializer):
    """
    Accepts a full MQTT connection config for onboarding "Test connection".
    """

    enabled = serializers.BooleanField(required=False, default=True)
    host = serializers.CharField(allow_blank=False)
    port = serializers.IntegerField(min_value=1, max_value=65535)
    username = serializers.CharField(required=False, allow_blank=True, default="")
    password = serializers.CharField(required=False, allow_blank=True, default="")
    use_tls = serializers.BooleanField(required=False, default=False)
    tls_insecure = serializers.BooleanField(required=False, default=False)
    client_id = serializers.CharField(required=False, allow_blank=True, default="latchpoint-alarm")
    keepalive_seconds = serializers.IntegerField(required=False, default=30, min_value=5, max_value=3600)
    connect_timeout_seconds = serializers.FloatField(required=False, default=5, min_value=0.5, max_value=30)

    def to_internal_value(self, data):
        """Normalize test-connection payload into a full connection settings dict."""
        value = super().to_internal_value(data)
        return normalize_mqtt_connection(value)


class HomeAssistantAlarmEntitySettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    entity_name = serializers.CharField(allow_blank=True)
    also_rename_in_home_assistant = serializers.BooleanField()
    ha_entity_id = serializers.CharField(allow_blank=True)


class HomeAssistantAlarmEntitySettingsUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    entity_name = serializers.CharField(required=False, allow_blank=True)
    also_rename_in_home_assistant = serializers.BooleanField(required=False)
    ha_entity_id = serializers.CharField(required=False, allow_blank=True)
