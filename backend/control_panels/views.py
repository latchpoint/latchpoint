from __future__ import annotations

import logging

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from config.domain_exceptions import ServiceUnavailableError, ValidationError
from config.view_utils import ObjectPermissionMixin
from control_panels.models import ControlPanelDevice
from control_panels.zwave_ring_keypad_v2 import test_ring_keypad_v2_beep
from control_panels.serializers import (
    ControlPanelDeviceCreateSerializer,
    ControlPanelDeviceSerializer,
    ControlPanelDeviceTestSerializer,
    ControlPanelDeviceUpdateSerializer,
)

logger = logging.getLogger(__name__)


def _assert_zwavejs_enabled() -> None:
    """Raise if Z-Wave JS is not enabled/configured in the active settings profile."""
    from alarm.state_machine.settings import get_active_settings_profile, get_setting_json

    profile = get_active_settings_profile()
    raw = get_setting_json(profile, "zwavejs_connection") or {}
    if not isinstance(raw, dict) or not raw.get("enabled") or not raw.get("ws_url"):
        raise ValueError("Z-Wave JS must be enabled and configured before adding a Z-Wave control panel.")


class ControlPanelDeviceListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """List configured control panel devices (admin-only)."""
        devices = ControlPanelDevice.objects.order_by("id")
        return Response(ControlPanelDeviceSerializer(devices, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a new control panel device (admin-only)."""
        serializer = ControlPanelDeviceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["integration_type"] == "zwavejs":
            try:
                _assert_zwavejs_enabled()
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        try:
            device = ControlPanelDevice.objects.create(
                name=data["name"],
                integration_type=data["integration_type"],
                kind=data["kind"],
                enabled=bool(data.get("enabled", True)),
                external_key=data["external_key"],
                external_id=data["external_id"],
                action_map=data.get("action_map") or {},
            )
        except IntegrityError:
            # external_key is unique; return a friendly 400 instead of a 500.
            raise ValidationError("A control panel is already configured for this device.")
        return Response(ControlPanelDeviceSerializer(device).data, status=status.HTTP_201_CREATED)


class ControlPanelDeviceDetailView(ObjectPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request, device_id: int):
        """Return a single control panel device (admin-only)."""
        device = self.get_object_or_404(request=request, queryset=ControlPanelDevice.objects.all(), id=device_id)
        return Response(ControlPanelDeviceSerializer(device).data, status=status.HTTP_200_OK)

    def patch(self, request, device_id: int):
        """Update a control panel device (admin-only)."""
        device = self.get_object_or_404(request=request, queryset=ControlPanelDevice.objects.all(), id=device_id)
        serializer = ControlPanelDeviceUpdateSerializer(data=request.data, partial=True, context={"device": device})
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)

        for field in ["name", "enabled", "external_id", "external_key", "last_error", "beep_volume"]:
            if field in changes:
                value = changes[field]
                if field == "external_key":
                    value = (value or "").strip()
                setattr(device, field, value)

        try:
            device.save()
        except IntegrityError:
            raise ValidationError("A control panel is already configured for this device.")
        return Response(ControlPanelDeviceSerializer(device).data, status=status.HTTP_200_OK)

    def delete(self, request, device_id: int):
        """Delete a control panel device (admin-only)."""
        device = self.get_object_or_404(request=request, queryset=ControlPanelDevice.objects.all(), id=device_id)
        device.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ControlPanelDeviceTestView(ObjectPermissionMixin, APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, device_id: int):
        """Run a best-effort test action (beep) for a control panel device (admin-only)."""
        device = self.get_object_or_404(request=request, queryset=ControlPanelDevice.objects.all(), id=device_id)

        serializer = ControlPanelDeviceTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        volume = serializer.validated_data.get("volume", device.beep_volume)

        try:
            # For now, only Ring Keypad v2 supports a simple "beep" test.
            test_ring_keypad_v2_beep(device=device, volume=volume)
        except NotImplementedError as exc:
            raise ValidationError(str(exc)) from exc
        except ValueError as exc:
            device.last_error = str(exc)
            device.save(update_fields=["last_error", "updated_at"])
            raise ValidationError(str(exc)) from exc
        except Exception as exc:
            device.last_error = str(exc)
            device.save(update_fields=["last_error", "updated_at"])
            logger.exception("Control panel test failed (device_id=%s)", device.id)
            raise ServiceUnavailableError("Failed to test control panel.") from exc

        device.last_error = ""
        device.last_seen_at = timezone.now()
        device.save(update_fields=["last_error", "last_seen_at", "updated_at"])
        return Response({"ok": True}, status=status.HTTP_200_OK)
