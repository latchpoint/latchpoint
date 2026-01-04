from __future__ import annotations

import logging

from django.utils import timezone
from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.models import AlarmSettingsEntry
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from alarm.signals import settings_profile_changed
from integrations_frigate.config import normalize_frigate_settings
from integrations_frigate.models import FrigateDetection
from integrations_frigate.runtime import (
    apply_runtime_settings_from_active_profile,
    get_last_error,
    get_last_ingest_at,
    is_available,
)
from integrations_frigate.serializers import (
    FrigateDetectionDetailSerializer,
    FrigateSettingsSerializer,
    FrigateSettingsUpdateSerializer,
)
from transports_mqtt.manager import mqtt_connection_manager

logger = logging.getLogger(__name__)


def _get_profile():
    """Return the active settings profile, creating one if needed."""
    return ensure_active_settings_profile()


class FrigateStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return Frigate runtime status including MQTT status and ingest/rules stats."""
        profile = _get_profile()
        settings_obj = normalize_frigate_settings(get_setting_json(profile, "frigate") or {})
        apply_runtime_settings_from_active_profile()
        return Response(
            {
                "enabled": settings_obj.enabled,
                "events_topic": settings_obj.events_topic,
                "retention_seconds": settings_obj.retention_seconds,
                "available": is_available(),
                "mqtt": mqtt_connection_manager.get_status().as_dict(),
                "ingest": {"last_ingest_at": get_last_ingest_at(), "last_error": get_last_error()},
            },
            status=status.HTTP_200_OK,
        )


class FrigateSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current persisted Frigate settings."""
        profile = _get_profile()
        value = normalize_frigate_settings(get_setting_json(profile, "frigate") or {})
        return Response(FrigateSettingsSerializer(value.__dict__).data, status=status.HTTP_200_OK)

    def patch(self, request):
        """Update Frigate settings and apply runtime changes (admin-only)."""
        profile = _get_profile()
        current = normalize_frigate_settings(get_setting_json(profile, "frigate") or {})

        serializer = FrigateSettingsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)

        if changes.get("enabled") is True:
            mqtt_conn = get_setting_json(profile, "mqtt_connection") or {}
            mqtt_ok = bool(isinstance(mqtt_conn, dict) and mqtt_conn.get("enabled") and mqtt_conn.get("host"))
            if not mqtt_ok:
                raise ValidationError({"non_field_errors": ["MQTT must be enabled/configured before enabling Frigate."]})

        merged = dict(current.__dict__)
        merged.update(changes)
        normalized = normalize_frigate_settings(merged)

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["frigate"]
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="frigate",
            defaults={"value": normalized.__dict__, "value_type": definition.value_type},
        )

        apply_runtime_settings_from_active_profile()
        transaction.on_commit(lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated"))
        return Response(FrigateSettingsSerializer(normalized.__dict__).data, status=status.HTTP_200_OK)


class FrigateOptionsView(APIView):
    """
    Helper endpoint for UI rule builders:
    returns known cameras/zones based on recently ingested detections.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return available cameras/zones for rule builders based on recent detections and config."""
        profile = _get_profile()
        settings_obj = normalize_frigate_settings(get_setting_json(profile, "frigate") or {})
        now = timezone.now()
        since = now - timezone.timedelta(seconds=int(settings_obj.retention_seconds))

        cameras_from_ingest = list(
            FrigateDetection.objects.filter(provider="frigate", observed_at__gte=since)
            .values_list("camera", flat=True)
            .distinct()
            .order_by("camera")
        )

        zones_by_camera: dict[str, set[str]] = {}
        zones_by_camera_out: dict[str, list[str]] = {}
        for row in (
            FrigateDetection.objects.filter(provider="frigate", observed_at__gte=since)
            .only("camera", "zones")
            .iterator()
        ):
            camera = (row.camera or "").strip()
            if not camera:
                continue
            zones = row.zones or []
            if not isinstance(zones, list):
                continue
            bucket = zones_by_camera.setdefault(camera, set())
            for z in zones:
                if isinstance(z, str) and z.strip():
                    bucket.add(z.strip())
        zones_by_camera_out = {cam: sorted(list(zones)) for cam, zones in zones_by_camera.items()}

        cameras = sorted(
            {
                *(settings_obj.known_cameras or []),
                *[c for c in cameras_from_ingest if isinstance(c, str) and c.strip()],
            }
        )
        # Merge configured zones with observed zones.
        for cam, zones in (settings_obj.known_zones_by_camera or {}).items():
            if not isinstance(cam, str) or not cam.strip():
                continue
            bucket = zones_by_camera_out.setdefault(cam.strip(), [])
            merged = sorted({*bucket, *[z for z in zones if isinstance(z, str) and z.strip()]})
            zones_by_camera_out[cam.strip()] = merged

        return Response(
            {
                "cameras": cameras,
                "zones_by_camera": zones_by_camera_out,
            },
            status=status.HTTP_200_OK,
        )


class FrigateDetectionsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the most recent person detections (admin-only, capped by limit)."""
        limit_raw = request.query_params.get("limit", "50")
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            logger.debug("Invalid frigate detections limit=%r; defaulting to 50", limit_raw)
            limit = 50
        limit = max(1, min(500, limit))
        rows = (
            FrigateDetection.objects.filter(provider="frigate", label="person")
            .order_by("-observed_at", "-id")[:limit]
        )
        return Response(
            [
                {
                    "id": r.id,
                    "event_id": r.event_id,
                    "camera": r.camera,
                    "zones": r.zones,
                    "confidence_pct": r.confidence_pct,
                    "observed_at": r.observed_at.isoformat(),
                }
                for r in rows
            ],
            status=status.HTTP_200_OK,
        )


class FrigateDetectionDetailView(APIView):
    """Return full detection details including raw JSON payload (admin-only)."""

    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request, pk: int):
        """Return full detection with raw JSON payload."""
        try:
            detection = FrigateDetection.objects.get(pk=pk)
        except FrigateDetection.DoesNotExist:
            raise NotFound("Detection not found.")

        serializer = FrigateDetectionDetailSerializer(detection)
        return Response(serializer.data, status=status.HTTP_200_OK)
