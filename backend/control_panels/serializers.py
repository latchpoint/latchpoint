from __future__ import annotations

from rest_framework import serializers

from control_panels.models import (
    ControlPanelAction,
    ControlPanelDevice,
    ControlPanelIntegrationType,
    ControlPanelKind,
)


def _build_external_key(*, integration_type: str, external_id: dict) -> str:
    """Build a stable external_key string from integration_type-specific external identifiers."""
    if integration_type == ControlPanelIntegrationType.ZWAVEJS:
        home_id = external_id.get("home_id")
        node_id = external_id.get("node_id")
        if not isinstance(home_id, int) or not isinstance(node_id, int):
            raise serializers.ValidationError("zwavejs external_id must include integer home_id and node_id.")
        return f"zwavejs:{home_id}:{node_id}"
    if integration_type == ControlPanelIntegrationType.HOME_ASSISTANT:
        device_id = external_id.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip():
            raise serializers.ValidationError("home_assistant external_id must include non-empty device_id.")
        return f"home_assistant:{device_id.strip()}"
    raise serializers.ValidationError("Unsupported integration_type.")


def _default_action_map_for_kind(kind: str) -> dict[str, str]:
    """Return the default action map for a given control panel kind."""
    if kind == ControlPanelKind.RING_KEYPAD_V2:
        return {
            ControlPanelAction.DISARM: "disarmed",
            ControlPanelAction.ARM_HOME: "armed_home",
            ControlPanelAction.ARM_AWAY: "armed_away",
            ControlPanelAction.CANCEL: "cancel_arming",
        }
    return {}


class ControlPanelDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlPanelDevice
        fields = [
            "id",
            "name",
            "integration_type",
            "kind",
            "enabled",
            "external_key",
            "external_id",
            "beep_volume",
            "last_seen_at",
            "last_error",
            "created_at",
            "updated_at",
        ]


class ControlPanelDeviceCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    integration_type = serializers.ChoiceField(choices=ControlPanelIntegrationType.choices)
    kind = serializers.ChoiceField(choices=ControlPanelKind.choices)
    enabled = serializers.BooleanField(default=True)
    external_id = serializers.JSONField(required=True)
    external_key = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate(self, attrs):
        """Validate external_id/external_key, ensure uniqueness, and populate default action_map."""
        external_id = attrs.get("external_id")
        if not isinstance(external_id, dict):
            raise serializers.ValidationError({"external_id": "Must be an object."})

        integration_type = attrs["integration_type"]
        external_key = (attrs.get("external_key") or "").strip()
        if not external_key:
            external_key = _build_external_key(integration_type=integration_type, external_id=external_id)
        attrs["external_key"] = external_key
        if ControlPanelDevice.objects.filter(external_key=external_key).exists():
            raise serializers.ValidationError("A control panel is already configured for this device.")

        # Action mapping is intentionally not configurable via API/UI.
        attrs["action_map"] = _default_action_map_for_kind(attrs["kind"])

        return attrs


class ControlPanelDeviceUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    enabled = serializers.BooleanField(required=False)
    external_id = serializers.JSONField(required=False)
    external_key = serializers.CharField(max_length=200, required=False, allow_blank=True)
    last_error = serializers.CharField(required=False, allow_blank=True)
    beep_volume = serializers.IntegerField(required=False, min_value=1, max_value=99)

    def validate(self, attrs):
        """Validate update inputs and keep external_key consistent with external_id."""
        device: ControlPanelDevice | None = self.context.get("device") if isinstance(self.context, dict) else None
        if device is None:
            raise serializers.ValidationError("Internal error: missing device context.")

        if "external_id" in attrs and not isinstance(attrs.get("external_id"), dict):
            raise serializers.ValidationError({"external_id": "Must be an object."})

        # If external_id is updated without an explicit external_key, keep external_key consistent.
        if "external_id" in attrs and "external_key" not in attrs:
            attrs["external_key"] = _build_external_key(
                integration_type=device.integration_type,
                external_id=attrs["external_id"],
            )

        # If external_key is provided blank, attempt to rebuild it from current/existing external_id.
        if "external_key" in attrs:
            attrs["external_key"] = (attrs.get("external_key") or "").strip()
            if not attrs["external_key"]:
                external_id = attrs.get("external_id") if "external_id" in attrs else device.external_id
                attrs["external_key"] = _build_external_key(
                    integration_type=device.integration_type,
                    external_id=external_id,
                )

        if "external_key" in attrs and attrs["external_key"]:
            if ControlPanelDevice.objects.filter(external_key=attrs["external_key"]).exclude(id=device.id).exists():
                raise serializers.ValidationError("A control panel is already configured for this device.")
        return attrs


class ControlPanelDeviceTestSerializer(serializers.Serializer):
    volume = serializers.IntegerField(required=False, min_value=1, max_value=99)
