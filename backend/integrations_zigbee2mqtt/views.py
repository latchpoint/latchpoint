from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from transports_mqtt.manager import mqtt_connection_manager

from accounts.permissions import IsAdminRole
from alarm.models import Entity
from alarm.serializers import EntitySerializer
from config.domain_exceptions import OperationTimeoutError, ServiceUnavailableError, ValidationError
from integrations_zigbee2mqtt.runtime import (
    apply_runtime_settings_from_active_profile,
    get_settings,
    sync_devices_via_mqtt,
)
from integrations_zigbee2mqtt.serializers import Zigbee2mqttSettingsSerializer
from integrations_zigbee2mqtt.status_store import get_last_seen_at, get_last_state, get_last_sync

_Z2M_ALIVE_GRACE_SECONDS = 75
logger = logging.getLogger(__name__)


class Zigbee2mqttStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return Zigbee2MQTT runtime status including MQTT status and last sync/seen info."""
        settings_obj = get_settings()
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
        """Return the current Zigbee2MQTT settings (read-only, from environment variables)."""
        settings_obj = get_settings()
        return Response(Zigbee2mqttSettingsSerializer(settings_obj.__dict__).data, status=status.HTTP_200_OK)

    def patch(self, request):
        """Zigbee2MQTT settings are now configured via environment variables."""
        raise MethodNotAllowed(request.method, detail="Zigbee2MQTT settings are configured via environment variables.")


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
