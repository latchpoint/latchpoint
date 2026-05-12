from __future__ import annotations

from rest_framework import serializers

from alarm.models import PendingAction


class PendingActionSerializer(serializers.ModelSerializer):
    """Read serializer for the PendingAction queue (ADR-0091)."""

    rule_name = serializers.CharField(source="rule.name", read_only=True)
    rule_id = serializers.IntegerField(source="rule.id", read_only=True)
    actor_user_email = serializers.SerializerMethodField()

    class Meta:
        model = PendingAction
        fields = [
            "id",
            "rule_id",
            "rule_name",
            "action_index",
            "action_payload",
            "delay_seconds",
            "scheduled_at",
            "fire_at",
            "status",
            "cancel_reason",
            "fired_at",
            "fire_result",
            "armed_state_at_schedule",
            "actor_user_email",
            "created_at",
            "updated_at",
        ]

    def get_actor_user_email(self, obj: PendingAction) -> str | None:
        return obj.actor_user.email if obj.actor_user else None
