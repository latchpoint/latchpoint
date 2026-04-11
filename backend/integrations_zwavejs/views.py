from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.models import AlarmSettingsEntry
from alarm.serializers import ZwavejsSetValueSerializer, ZwavejsTestConnectionSerializer
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.signals import settings_profile_changed
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from config.domain_exceptions import ServiceUnavailableError, ValidationError
from integrations_zwavejs.entity_sync import sync_entities_from_zwavejs

zwavejs_gateway = default_zwavejs_gateway
logger = logging.getLogger(__name__)


def _get_entry(profile=None) -> AlarmSettingsEntry:
    """Return (or create) the zwavejs AlarmSettingsEntry for the active profile."""
    if profile is None:
        profile = ensure_active_settings_profile()
    definition = ALARM_PROFILE_SETTINGS_BY_KEY["zwavejs"]
    entry, _ = AlarmSettingsEntry.objects.get_or_create(
        profile=profile,
        key="zwavejs",
        defaults={"value": definition.default, "value_type": definition.value_type},
    )
    return entry


def get_zwavejs_settings() -> dict:
    """Return decrypted Z-Wave JS settings for runtime consumers (gateways, commands)."""
    return _get_entry().get_decrypted_value()


def _extract_nodes(controller_state: dict) -> list[dict]:
    """Normalize controller state into a list of node dicts across known response shapes."""
    state = controller_state.get("state") if isinstance(controller_state.get("state"), dict) else controller_state
    nodes = state.get("nodes") if isinstance(state, dict) else None
    if isinstance(nodes, list):
        return nodes
    if isinstance(nodes, dict):
        out: list[dict] = []
        for key, value in nodes.items():
            if not isinstance(value, dict):
                continue
            if "id" in value or "nodeId" in value:
                out.append(value)
                continue
            node_id = None
            if isinstance(key, int):
                node_id = key
            elif isinstance(key, str) and key.isdigit():
                node_id = int(key)
            if node_id is None:
                out.append(value)
                continue
            merged = dict(value)
            merged["id"] = node_id
            out.append(merged)
        return out
    return []


def _node_summary(node: dict) -> dict:
    """Return a small UI-friendly summary for a raw Z-Wave node dict."""
    node_id = node.get("id") if isinstance(node.get("id"), int) else node.get("nodeId")
    name = node.get("name") if isinstance(node.get("name"), str) else None
    label = node.get("label") if isinstance(node.get("label"), str) else None
    product_label = node.get("productLabel") if isinstance(node.get("productLabel"), str) else None
    manufacturer = None
    if isinstance(node.get("manufacturer"), dict):
        manufacturer = node["manufacturer"].get("name")
    manufacturer = manufacturer if isinstance(manufacturer, str) else node.get("manufacturer")

    command_classes = None
    cc_obj = node.get("commandClasses")
    if isinstance(cc_obj, dict):
        command_classes = sorted([str(k) for k in cc_obj])
    return {
        "node_id": node_id,
        "name": name or label or product_label or (f"Node {node_id}" if node_id else "Unknown node"),
        "manufacturer": manufacturer if isinstance(manufacturer, str) else None,
        "product_label": product_label,
        "command_classes": command_classes,
        "raw": {"id": node_id, "label": label, "productLabel": product_label},
    }


def _ensure_zwavejs_ready() -> None:
    """Read decrypted settings and ensure gateway is connected."""
    settings = get_zwavejs_settings()
    if not settings.get("enabled"):
        raise ValidationError("Z-Wave JS is disabled.")
    if not settings.get("ws_url"):
        raise ValidationError("Z-Wave JS ws_url is required.")
    zwavejs_gateway.apply_settings(settings_obj=settings)
    zwavejs_gateway.ensure_connected(timeout_seconds=float(settings.get("connect_timeout_seconds") or 5))


class ZwavejsStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current Z-Wave JS connection status."""
        settings = get_zwavejs_settings()
        zwavejs_gateway.apply_settings(settings_obj=settings)
        return Response(zwavejs_gateway.get_status().as_dict(), status=status.HTTP_200_OK)


class ZwavejsSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return Z-Wave JS settings with secrets masked."""
        entry = _get_entry()
        return Response(entry.get_masked_value_with_defaults(), status=status.HTTP_200_OK)

    def patch(self, request):
        """Update Z-Wave JS settings (connection + operational)."""
        data = request.data
        if not isinstance(data, dict) or not data:
            raise ValidationError("Request body must be a non-empty object.")

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["zwavejs"]
        allowed = set(definition.config_schema["properties"])
        invalid = set(data) - allowed
        if invalid:
            raise ValidationError(f"Unknown fields: {', '.join(sorted(invalid))}")

        profile = ensure_active_settings_profile()
        entry = _get_entry(profile)
        entry.set_value_with_encryption(data)

        settings = entry.get_decrypted_value()
        zwavejs_gateway.apply_settings(settings_obj=settings)
        transaction.on_commit(
            lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated")
        )
        return Response(entry.get_masked_value_with_defaults(), status=status.HTTP_200_OK)


class ZwavejsTestConnectionView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Test a Z-Wave JS connection without persisting settings."""
        serializer = ZwavejsTestConnectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.validated_data

        if not settings_obj.get("ws_url"):
            raise ValidationError("Z-Wave JS ws_url is required.")
        zwavejs_gateway.test_connection(
            settings_obj=settings_obj, timeout_seconds=settings_obj.get("connect_timeout_seconds")
        )
        return Response({"ok": True}, status=status.HTTP_200_OK)


class ZwavejsEntitySyncView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Sync entities from Z-Wave JS into the local entity registry (admin-only)."""
        _ensure_zwavejs_ready()

        try:
            result = sync_entities_from_zwavejs(zwavejs=zwavejs_gateway)
        except Exception as exc:
            logger.exception("Z-Wave JS entity sync failed")
            raise ServiceUnavailableError("Failed to sync Z-Wave JS entities.") from exc
        return Response(result, status=status.HTTP_200_OK)


class ZwavejsSetValueView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Write a Z-Wave value to a node via zwave-js-server (admin-only)."""
        serializer = ZwavejsSetValueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        _ensure_zwavejs_ready()

        zwavejs_gateway.set_value(
            node_id=int(payload["node_id"]),
            endpoint=int(payload.get("endpoint") or 0),
            command_class=int(payload["command_class"]),
            property=payload["property"],
            property_key=payload.get("property_key"),
            value=payload["value"],
        )

        return Response({"ok": True}, status=status.HTTP_200_OK)


class ZwavejsNodesView(APIView):
    """Best-effort node listing for UI discovery."""

    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return a best-effort list of controller nodes for UI discovery (admin-only)."""
        _ensure_zwavejs_ready()

        try:
            controller_state = zwavejs_gateway.controller_get_state(timeout_seconds=10)
            nodes = _extract_nodes(controller_state if isinstance(controller_state, dict) else {})
        except Exception as exc:
            logger.exception("Failed to fetch Z-Wave JS nodes")
            raise ServiceUnavailableError("Failed to fetch Z-Wave JS nodes.") from exc

        home_id = zwavejs_gateway.get_home_id()
        summaries = [_node_summary(node) for node in nodes if isinstance(node, dict)]
        summaries = [row for row in summaries if isinstance(row.get("node_id"), int)]
        summaries.sort(key=lambda r: int(r.get("node_id") or 0))
        return Response({"home_id": home_id, "nodes": summaries}, status=status.HTTP_200_OK)
