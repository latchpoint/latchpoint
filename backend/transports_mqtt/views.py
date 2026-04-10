from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.env_config import get_mqtt_config
from alarm.gateways.mqtt import default_mqtt_gateway
from alarm.models import AlarmSettingsEntry
from alarm.serializers import MqttTestConnectionSerializer
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.signals import settings_profile_changed
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from config.domain_exceptions import ValidationError

mqtt_gateway = default_mqtt_gateway


def _get_mqtt_settings() -> dict:
    """Return merged MQTT settings: env connection config + DB operational overrides."""
    cfg = get_mqtt_config()
    profile = ensure_active_settings_profile()
    db_settings = get_setting_json(profile, "mqtt") or {}
    if not isinstance(db_settings, dict):
        db_settings = {}
    return {
        "enabled": cfg["enabled"],
        "host": cfg["host"],
        "port": cfg["port"],
        "username": cfg["username"],
        "password": cfg["password"],
        "use_tls": cfg["use_tls"],
        "tls_insecure": cfg["tls_insecure"],
        "client_id": cfg["client_id"],
        "keepalive_seconds": int(db_settings.get("keepalive_seconds", cfg["keepalive_seconds"])),
        "connect_timeout_seconds": int(db_settings.get("connect_timeout_seconds", cfg["connect_timeout_seconds"])),
    }


def _mqtt_response(settings: dict) -> dict:
    """Build the API response dict (masks password)."""
    return {
        "enabled": settings["enabled"],
        "host": settings["host"],
        "port": settings["port"],
        "username": settings["username"],
        "has_password": bool(settings.get("password")),
        "use_tls": settings["use_tls"],
        "tls_insecure": settings["tls_insecure"],
        "client_id": settings["client_id"],
        "keepalive_seconds": settings["keepalive_seconds"],
        "connect_timeout_seconds": settings["connect_timeout_seconds"],
    }


class MqttStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current MQTT connection status."""
        status_obj = mqtt_gateway.get_status().as_dict()
        return Response(status_obj, status=status.HTTP_200_OK)


class MqttSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current MQTT connection settings (env) + operational settings (DB)."""
        settings = _get_mqtt_settings()
        return Response(_mqtt_response(settings), status=status.HTTP_200_OK)

    def patch(self, request):
        """Update MQTT operational settings (admin-only)."""
        data = request.data
        if not isinstance(data, dict) or not data:
            raise ValidationError("Request body must be a non-empty object.")

        profile = ensure_active_settings_profile()
        current = get_setting_json(profile, "mqtt") or {}
        if not isinstance(current, dict):
            current = {}

        if "keepalive_seconds" in data:
            val = data["keepalive_seconds"]
            if not isinstance(val, int) or val < 1 or val > 3600:
                raise ValidationError("keepalive_seconds must be an integer between 1 and 3600.")
            current["keepalive_seconds"] = val
        if "connect_timeout_seconds" in data:
            val = data["connect_timeout_seconds"]
            if not isinstance(val, int) or val < 1 or val > 300:
                raise ValidationError("connect_timeout_seconds must be an integer between 1 and 300.")
            current["connect_timeout_seconds"] = val

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["mqtt"]
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="mqtt",
            defaults={"value": current, "value_type": definition.value_type},
        )

        settings = _get_mqtt_settings()
        mqtt_gateway.apply_settings(settings=settings)
        transaction.on_commit(
            lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated")
        )
        return Response(_mqtt_response(settings), status=status.HTTP_200_OK)


class MqttTestConnectionView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Test an MQTT connection without persisting settings."""
        serializer = MqttTestConnectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.validated_data
        mqtt_gateway.test_connection(settings=settings_obj)
        return Response({"ok": True}, status=status.HTTP_200_OK)
