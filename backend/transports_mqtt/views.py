from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.gateways.mqtt import default_mqtt_gateway
from alarm.models import AlarmSettingsEntry
from alarm.serializers import MqttTestConnectionSerializer
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.signals import settings_profile_changed
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from config.domain_exceptions import ValidationError

mqtt_gateway = default_mqtt_gateway


def _get_entry(profile=None) -> AlarmSettingsEntry:
    """Return (or create) the mqtt AlarmSettingsEntry for the active profile."""
    if profile is None:
        profile = ensure_active_settings_profile()
    definition = ALARM_PROFILE_SETTINGS_BY_KEY["mqtt"]
    entry, _ = AlarmSettingsEntry.objects.get_or_create(
        profile=profile,
        key="mqtt",
        defaults={"value": definition.default, "value_type": definition.value_type},
    )
    return entry


def get_mqtt_settings() -> dict:
    """Return decrypted MQTT settings for runtime consumers (gateways, commands)."""
    return _get_entry().get_decrypted_value()


class MqttStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current MQTT connection status."""
        status_obj = mqtt_gateway.get_status().as_dict()
        return Response(status_obj, status=status.HTTP_200_OK)


class MqttSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return MQTT settings with secrets masked."""
        entry = _get_entry()
        return Response(entry.get_masked_value_with_defaults(), status=status.HTTP_200_OK)

    def patch(self, request):
        """Update MQTT settings (connection + operational)."""
        data = request.data
        if not isinstance(data, dict) or not data:
            raise ValidationError("Request body must be a non-empty object.")

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["mqtt"]
        allowed = set(definition.config_schema["properties"])
        invalid = set(data) - allowed
        if invalid:
            raise ValidationError(f"Unknown fields: {', '.join(sorted(invalid))}")

        profile = ensure_active_settings_profile()
        entry = _get_entry(profile)
        entry.set_value_with_encryption(data)

        settings = entry.get_decrypted_value()
        mqtt_gateway.apply_settings(settings=settings)
        transaction.on_commit(
            lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated")
        )
        return Response(entry.get_masked_value_with_defaults(), status=status.HTTP_200_OK)


class MqttTestConnectionView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Test an MQTT connection without persisting settings."""
        serializer = MqttTestConnectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.validated_data
        mqtt_gateway.test_connection(settings=settings_obj)
        return Response({"ok": True}, status=status.HTTP_200_OK)
