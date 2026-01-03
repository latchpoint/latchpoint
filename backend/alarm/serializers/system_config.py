from __future__ import annotations

import re

from rest_framework import serializers

from alarm.models import SystemConfig, SystemConfigValueType

KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


def _validate_value_type_pair(value_type: str, value):
    """Validate a SystemConfig (value_type, value) pair, raising DRF ValidationError on mismatch."""
    if value_type == SystemConfigValueType.BOOLEAN:
        if not isinstance(value, bool):
            raise serializers.ValidationError("Value must be a boolean.")
        return

    if value_type == SystemConfigValueType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise serializers.ValidationError("Value must be an integer.")
        return

    if value_type == SystemConfigValueType.FLOAT:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise serializers.ValidationError("Value must be a number.")
        return

    if value_type == SystemConfigValueType.STRING:
        if not isinstance(value, str):
            raise serializers.ValidationError("Value must be a string.")
        return

    if value_type == SystemConfigValueType.JSON:
        return

    raise serializers.ValidationError("Invalid value type.")


class SystemConfigSerializer(serializers.ModelSerializer):
    modified_by_id = serializers.UUIDField(allow_null=True, read_only=True)

    class Meta:
        model = SystemConfig
        fields = (
            "key",
            "name",
            "value_type",
            "value",
            "description",
            "modified_by_id",
            "created_at",
            "updated_at",
        )


class SystemConfigCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemConfig
        fields = (
            "key",
            "name",
            "value_type",
            "value",
            "description",
        )

    def validate_key(self, value: str) -> str:
        """Validate and normalize the SystemConfig key."""
        key = value.strip()
        if not KEY_RE.match(key):
            raise serializers.ValidationError("Key must be lowercase and contain only a-z, 0-9, '_', '.', or '-'.")
        return key

    def validate(self, attrs):
        """Validate that `value` matches `value_type`."""
        value_type = attrs.get("value_type")
        value = attrs.get("value")
        _validate_value_type_pair(value_type, value)
        return attrs


class SystemConfigUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemConfig
        fields = (
            "value",
            "description",
        )

    def validate(self, attrs):
        """Validate updated value against existing `value_type`."""
        value_type = self.instance.value_type
        value = attrs.get("value", self.instance.value)
        _validate_value_type_pair(value_type, value)
        return attrs
