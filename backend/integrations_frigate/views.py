from __future__ import annotations

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from transports_mqtt.manager import mqtt_connection_manager

from accounts.permissions import IsAdminRole
from integrations_frigate.models import FrigateDetection
from integrations_frigate.runtime import (
    apply_runtime_settings_from_active_profile,
    get_last_error,
    get_last_ingest_at,
    get_settings,
    is_available,
)
from integrations_frigate.serializers import (
    FrigateDetectionDetailSerializer,
    FrigateSettingsSerializer,
)

logger = logging.getLogger(__name__)


class FrigateStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return Frigate runtime status including MQTT status and ingest/rules stats."""
        settings_obj = get_settings()
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
        """Return the current Frigate settings (read-only, from environment variables)."""
        value = get_settings()
        return Response(FrigateSettingsSerializer(value.__dict__).data, status=status.HTTP_200_OK)

    def patch(self, request):
        """Frigate settings are now configured via environment variables."""
        raise MethodNotAllowed(request.method, detail="Frigate settings are configured via environment variables.")


class FrigateOptionsView(APIView):
    """
    Helper endpoint for UI rule builders:
    returns known cameras/zones auto-discovered from recent detections (ADR 0078).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return available cameras/zones for rule builders based on recent detections."""
        settings_obj = get_settings()
        now = timezone.now()
        since = now - timezone.timedelta(seconds=int(settings_obj.retention_seconds))

        cameras = list(
            FrigateDetection.objects.filter(provider="frigate", observed_at__gte=since)
            .values_list("camera", flat=True)
            .distinct()
            .order_by("camera")
        )

        zones_by_camera: dict[str, set[str]] = {}
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

        return Response(
            {
                "cameras": [c.strip() for c in cameras if isinstance(c, str) and c.strip()],
                "zones_by_camera": {cam: sorted(zones) for cam, zones in zones_by_camera.items()},
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
        rows = FrigateDetection.objects.filter(provider="frigate", label="person").order_by("-observed_at", "-id")[
            :limit
        ]
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
        except FrigateDetection.DoesNotExist as exc:
            raise NotFound("Detection not found.") from exc

        serializer = FrigateDetectionDetailSerializer(detection)
        return Response(serializer.data, status=status.HTTP_200_OK)
