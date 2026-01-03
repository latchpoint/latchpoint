from __future__ import annotations

from rest_framework import serializers


class Zigbee2mqttSettingsSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    base_topic = serializers.CharField()
    allowlist = serializers.ListField(required=False)
    denylist = serializers.ListField(required=False)
    run_rules_on_event = serializers.BooleanField(required=False)
    run_rules_debounce_seconds = serializers.IntegerField(required=False)
    run_rules_max_per_minute = serializers.IntegerField(required=False)
    run_rules_kinds = serializers.ListField(child=serializers.CharField(), required=False)


class Zigbee2mqttSettingsUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    base_topic = serializers.CharField(required=False, allow_blank=True)
    allowlist = serializers.ListField(required=False)
    denylist = serializers.ListField(required=False)
    run_rules_on_event = serializers.BooleanField(required=False)
    run_rules_debounce_seconds = serializers.IntegerField(required=False)
    run_rules_max_per_minute = serializers.IntegerField(required=False)
    run_rules_kinds = serializers.ListField(child=serializers.CharField(), required=False)

