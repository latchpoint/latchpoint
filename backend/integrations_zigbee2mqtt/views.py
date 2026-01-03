from __future__ import annotations

import logging

from django.utils import timezone
from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from config.domain_exceptions import OperationTimeoutError, ServiceUnavailableError, ValidationError
from alarm.models import AlarmSettingsEntry, Entity
from alarm.serializers import EntitySerializer
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from alarm.signals import settings_profile_changed
from integrations_zigbee2mqtt.config import (
    mask_zigbee2mqtt_settings,
    normalize_zigbee2mqtt_settings,
)
from integrations_zigbee2mqtt.serializers import (
    Zigbee2mqttSettingsSerializer,
    Zigbee2mqttSettingsUpdateSerializer,
)
from integrations_zigbee2mqtt.status_store import get_last_sync
from integrations_zigbee2mqtt.status_store import get_last_seen_at, get_last_state
from integrations_zigbee2mqtt.runtime import apply_runtime_settings_from_active_profile, sync_devices_via_mqtt
from transports_mqtt.manager import mqtt_connection_manager

_Z2M_ALIVE_GRACE_SECONDS = 75
logger = logging.getLogger(__name__)


def _get_profile():
    """Return the active settings profile, creating one if needed."""
    return ensure_active_settings_profile()


class Zigbee2mqttStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return Zigbee2MQTT runtime status including MQTT status and last sync/seen info."""
        profile = _get_profile()
        settings_obj = normalize_zigbee2mqtt_settings(get_setting_json(profile, "zigbee2mqtt") or {})
        apply_runtime_settings_from_active_profile()
        mqtt_status = mqtt_connection_manager.get_status()
        now = timezone.now()
        state = (get_last_state() or "").strip().lower()
        connected = False
        if settings_obj.enabled and mqtt_status.connected and state != "offline":
            last_seen = get_last_seen_at()
            if last_seen:
                try:
                    last_dt = timezone.datetime.fromisoformat(last_seen)
                    last_dt = timezone.make_aware(last_dt) if timezone.is_naive(last_dt) else last_dt
                    connected = (now - last_dt) <= timezone.timedelta(seconds=_Z2M_ALIVE_GRACE_SECONDS)
                except ValueError:
                    connected = False
        return Response(
            {
                "enabled": settings_obj.enabled,
                "base_topic": settings_obj.base_topic,
                "connected": connected,
                "mqtt": mqtt_status.as_dict(),
                "sync": get_last_sync().as_dict(),
                "run_rules_on_event": settings_obj.run_rules_on_event,
                "run_rules_debounce_seconds": settings_obj.run_rules_debounce_seconds,
                "run_rules_max_per_minute": settings_obj.run_rules_max_per_minute,
                "run_rules_kinds": settings_obj.run_rules_kinds,
            },
            status=status.HTTP_200_OK,
        )


class Zigbee2mqttSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current Zigbee2MQTT settings."""
        profile = _get_profile()
        value = mask_zigbee2mqtt_settings(get_setting_json(profile, "zigbee2mqtt") or {})
        return Response(Zigbee2mqttSettingsSerializer(value).data, status=status.HTTP_200_OK)

    def patch(self, request):
        """Update Zigbee2MQTT settings and apply runtime changes (admin-only)."""
        profile = _get_profile()
        current = normalize_zigbee2mqtt_settings(get_setting_json(profile, "zigbee2mqtt") or {})

        serializer = Zigbee2mqttSettingsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)

        if changes.get("enabled") is True:
            mqtt_conn = get_setting_json(profile, "mqtt_connection") or {}
            mqtt_ok = bool(isinstance(mqtt_conn, dict) and mqtt_conn.get("enabled") and mqtt_conn.get("host"))
            if not mqtt_ok:
                raise ValidationError("MQTT must be enabled/configured before enabling Zigbee2MQTT.")

        merged = dict(current.__dict__)
        merged.update(changes)
        normalized = normalize_zigbee2mqtt_settings(merged)

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["zigbee2mqtt"]
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="zigbee2mqtt",
            defaults={"value": normalized.__dict__, "value_type": definition.value_type},
        )

        apply_runtime_settings_from_active_profile()
        transaction.on_commit(lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated"))
        return Response(
            Zigbee2mqttSettingsSerializer(mask_zigbee2mqtt_settings(normalized.__dict__)).data,
            status=status.HTTP_200_OK,
        )


class Zigbee2mqttDevicesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List locally stored Zigbee2MQTT entities."""
        queryset = Entity.objects.filter(source="zigbee2mqtt").order_by("entity_id")
        return Response(EntitySerializer(queryset, many=True).data, status=status.HTTP_200_OK)


class Zigbee2mqttDevicesSyncView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Run a best-effort inventory sync via MQTT and upsert local entities (admin-only)."""
        try:
            result = sync_devices_via_mqtt(timeout_seconds=10.0)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        except TimeoutError as exc:
            raise OperationTimeoutError(str(exc)) from exc
        except Exception as exc:
            logger.exception("Zigbee2MQTT device sync failed")
            raise ServiceUnavailableError("Failed to sync Zigbee2MQTT devices.") from exc
        return Response(result, status=status.HTTP_200_OK)
