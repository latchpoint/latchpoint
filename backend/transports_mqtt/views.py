from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db import transaction

from accounts.permissions import IsAdminRole
from config.domain_exceptions import ValidationError
from alarm.crypto import can_encrypt, encrypt_secret
from alarm.gateways.mqtt import default_mqtt_gateway
from transports_mqtt.config import normalize_mqtt_connection, prepare_runtime_mqtt_connection
from alarm.serializers import (
    MqttConnectionSettingsSerializer,
    MqttConnectionSettingsUpdateSerializer,
    MqttTestConnectionSerializer,
)
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from alarm.models import AlarmSettingsEntry
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.signals import settings_profile_changed


mqtt_gateway = default_mqtt_gateway


def _get_profile():
    """Return the active settings profile, creating one if needed."""
    return ensure_active_settings_profile()


def _get_mqtt_connection_value(profile):
    """Return normalized MQTT connection settings for the given profile."""
    return normalize_mqtt_connection(get_setting_json(profile, "mqtt_connection") or {})


class MqttStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current MQTT connection status (best-effort applies stored settings)."""
        # Best-effort: ensure the gateway has the persisted settings applied so status reflects reality.
        profile = _get_profile()
        settings_obj = _get_mqtt_connection_value(profile)
        mqtt_gateway.apply_settings(settings=prepare_runtime_mqtt_connection(settings_obj))
        status_obj = mqtt_gateway.get_status().as_dict()
        return Response(status_obj, status=status.HTTP_200_OK)


class MqttSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current persisted MQTT connection settings."""
        profile = _get_profile()
        value = _get_mqtt_connection_value(profile)
        return Response(MqttConnectionSettingsSerializer(value).data, status=status.HTTP_200_OK)

    def patch(self, request):
        """Update persisted MQTT settings, apply them, and disable dependent integrations when disabling MQTT."""
        profile = _get_profile()
        current = _get_mqtt_connection_value(profile)
        serializer = MqttConnectionSettingsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)

        if "password" in changes:
            if changes.get("password") and not can_encrypt():
                raise ValidationError("Encryption is not configured. Set SETTINGS_ENCRYPTION_KEY before saving secrets.")
            changes["password"] = encrypt_secret(changes.get("password"))
        else:
            # Preserve existing password token if not provided.
            changes["password"] = current.get("password", "")

        merged = dict(current)
        merged.update(changes)

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["mqtt_connection"]
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="mqtt_connection",
            defaults={"value": merged, "value_type": definition.value_type},
        )

        # Best-effort: refresh gateway connection state based on stored config.
        mqtt_gateway.apply_settings(settings=prepare_runtime_mqtt_connection(merged))

        # Hard coupling: MQTT is required for certain integrations.
        # If MQTT is disabled, automatically disable those integrations in the active profile.
        if not bool(merged.get("enabled", False)):
            for key in ["zigbee2mqtt", "frigate"]:
                raw = get_setting_json(profile, key) or {}
                if not isinstance(raw, dict):
                    raw = {}
                if raw.get("enabled") is not True:
                    continue
                next_value = dict(raw)
                next_value["enabled"] = False
                definition_other = ALARM_PROFILE_SETTINGS_BY_KEY.get(key)
                if not definition_other:
                    continue
                AlarmSettingsEntry.objects.update_or_create(
                    profile=profile,
                    key=key,
                    defaults={"value": next_value, "value_type": definition_other.value_type},
                )

        transaction.on_commit(lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated"))
        return Response(MqttConnectionSettingsSerializer(merged).data, status=status.HTTP_200_OK)


class MqttTestConnectionView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Test an MQTT connection without persisting settings."""
        serializer = MqttTestConnectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.validated_data
        mqtt_gateway.test_connection(settings=settings_obj)
        return Response({"ok": True}, status=status.HTTP_200_OK)
