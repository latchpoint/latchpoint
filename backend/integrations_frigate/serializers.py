from __future__ import annotations

from rest_framework import serializers

from integrations_frigate.models import FrigateDetection


class FrigateDetectionDetailSerializer(serializers.ModelSerializer):
    """Full serializer for FrigateDetection including raw JSON payload."""

    class Meta:
        model = FrigateDetection
        fields = [
            "id",
            "event_id",
            "provider",
            "label",
            "camera",
            "zones",
            "confidence_pct",
            "observed_at",
            "source_topic",
            "created_at",
            "updated_at",
            "raw",
        ]


class FrigateSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    events_topic = serializers.CharField()
    retention_seconds = serializers.IntegerField()
