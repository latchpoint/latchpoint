from __future__ import annotations

from rest_framework import serializers


class HomeAssistantConnectionSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    base_url = serializers.CharField(required=False, allow_blank=True)
    connect_timeout_seconds = serializers.FloatField(required=False)
    has_token = serializers.BooleanField(required=False)
