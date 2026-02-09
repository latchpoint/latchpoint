from __future__ import annotations

from rest_framework import serializers

from alarm.models import AlarmEvent, AlarmSettingsProfile, AlarmStateSnapshot
from alarm.integration_settings_masking import mask_setting_value
from alarm.settings_registry import ALARM_PROFILE_SETTINGS
from alarm.state_machine.settings import get_setting_json


def _list_profile_setting_entries(profile: AlarmSettingsProfile) -> list[dict[str, object]]:
    """Materialize settings entry rows for a profile from the settings registry."""
    out: list[dict[str, object]] = []
    for definition in ALARM_PROFILE_SETTINGS:
        value = get_setting_json(profile, definition.key)
        value = mask_setting_value(key=definition.key, value=value)
        out.append(
            {
                "key": definition.key,
                "name": definition.name,
                "value_type": definition.value_type,
                "value": value,
                "description": definition.description,
            }
        )
    return out


class AlarmStateSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlarmStateSnapshot
        fields = (
            "id",
            "current_state",
            "previous_state",
            "target_armed_state",
            "settings_profile",
            "entered_at",
            "exit_at",
            "last_transition_reason",
            "last_transition_by",
            "timing_snapshot",
        )


class AlarmSettingsProfileMetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlarmSettingsProfile
        fields = (
            "id",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        )



class AlarmEventSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(allow_null=True, read_only=True)
    code_id = serializers.IntegerField(allow_null=True, read_only=True)
    sensor_id = serializers.IntegerField(allow_null=True, read_only=True)

    class Meta:
        model = AlarmEvent
        fields = (
            "id",
            "event_type",
            "state_from",
            "state_to",
            "timestamp",
            "user_id",
            "code_id",
            "sensor_id",
            "metadata",
        )


class AlarmSettingsEntrySerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField(read_only=True)
    value_type = serializers.CharField(read_only=True)
    value = serializers.JSONField()
    description = serializers.CharField(read_only=True)


class AlarmSettingsProfileDetailSerializer(serializers.Serializer):
    profile = AlarmSettingsProfileMetaSerializer()
    entries = AlarmSettingsEntrySerializer(many=True)

    def to_representation(self, instance: AlarmSettingsProfile):
        """Return nested profile metadata plus a materialized list of entries."""
        return {
            "profile": AlarmSettingsProfileMetaSerializer(instance).data,
            "entries": _list_profile_setting_entries(instance),
        }


class AlarmSettingsProfileUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)

    class EntryUpdateSerializer(serializers.Serializer):
        key = serializers.CharField()
        value = serializers.JSONField()

    entries = EntryUpdateSerializer(many=True, required=False)
