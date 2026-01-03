from __future__ import annotations

from rest_framework import serializers

from alarm.models import Entity


class EntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Entity
        fields = (
            "id",
            "entity_id",
            "domain",
            "name",
            "device_class",
            "last_state",
            "last_changed",
            "last_seen",
            "attributes",
            "source",
            "created_at",
            "updated_at",
        )

