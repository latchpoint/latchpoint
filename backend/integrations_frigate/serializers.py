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
    run_rules_on_event = serializers.BooleanField()
    run_rules_debounce_seconds = serializers.IntegerField()
    run_rules_max_per_minute = serializers.IntegerField()
    run_rules_kinds = serializers.ListField(child=serializers.CharField(), required=False)
    known_cameras = serializers.ListField(child=serializers.CharField(), required=False)
    known_zones_by_camera = serializers.DictField(required=False)


class FrigateSettingsUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    events_topic = serializers.CharField(required=False, allow_blank=True)
    retention_seconds = serializers.IntegerField(required=False)
    run_rules_on_event = serializers.BooleanField(required=False)
    run_rules_debounce_seconds = serializers.IntegerField(required=False)
    run_rules_max_per_minute = serializers.IntegerField(required=False)
    run_rules_kinds = serializers.ListField(child=serializers.CharField(), required=False)
    known_cameras = serializers.ListField(child=serializers.CharField(), required=False)
    known_zones_by_camera = serializers.DictField(required=False)
