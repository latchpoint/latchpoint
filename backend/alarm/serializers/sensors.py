from __future__ import annotations

from rest_framework import serializers

from alarm.domain.entity_state import normalize_contact_state
from alarm.models import Sensor


class SensorSerializer(serializers.ModelSerializer):
    entity_id = serializers.CharField(allow_blank=True, required=False)
    current_state = serializers.SerializerMethodField()
    last_triggered = serializers.SerializerMethodField()
    used_in_rules = serializers.SerializerMethodField()

    class Meta:
        model = Sensor
        fields = (
            "id",
            "name",
            "entity_id",
            "is_active",
            "is_entry_point",
            "current_state",
            "last_triggered",
            "used_in_rules",
        )

    def get_current_state(self, obj: Sensor) -> str:
        """Return normalized current entity state for this sensor from serializer context."""
        entity_id = (obj.entity_id or "").strip()
        if not entity_id:
            return "unknown"
        state_map = self.context.get("entity_state_by_entity_id")
        if isinstance(state_map, dict):
            return normalize_contact_state(state_map.get(entity_id))
        return "unknown"

    def get_last_triggered(self, obj: Sensor):
        """Return ISO timestamp of last trigger event for this sensor, if known."""
        last_triggered_map = self.context.get("last_triggered_by_sensor_id")
        if isinstance(last_triggered_map, dict):
            value = last_triggered_map.get(obj.id)
            return value.isoformat() if value is not None else None
        return None

    def get_used_in_rules(self, obj: Sensor) -> bool:
        """Return True if this sensor's entity_id is referenced by any enabled rule."""
        entity_id = (obj.entity_id or "").strip()
        if not entity_id:
            return False
        used_set = self.context.get("used_entity_ids_in_rules")
        if isinstance(used_set, set):
            return entity_id in used_set
        if isinstance(used_set, (list, tuple)):
            return entity_id in set(used_set)
        return False


class SensorCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = (
            "id",
            "name",
            "entity_id",
            "is_active",
            "is_entry_point",
        )

    def validate_entity_id(self, value: str) -> str:
        """Validate and normalize Home Assistant-style entity ids."""
        entity_id = (value or "").strip()
        if not entity_id:
            raise serializers.ValidationError("entity_id is required.")
        if "." not in entity_id:
            raise serializers.ValidationError("Invalid entity_id.")
        return entity_id


class SensorUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sensor
        fields = (
            "id",
            "name",
            "is_active",
            "is_entry_point",
        )
