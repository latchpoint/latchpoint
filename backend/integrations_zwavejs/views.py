from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.db import transaction

from accounts.permissions import IsAdminRole
from config.domain_exceptions import ServiceUnavailableError, ValidationError
from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.models import AlarmSettingsEntry
from alarm.serializers import (
    ZwavejsConnectionSettingsSerializer,
    ZwavejsConnectionSettingsUpdateSerializer,
    ZwavejsSetValueSerializer,
    ZwavejsTestConnectionSerializer,
)
from alarm.settings_registry import ALARM_PROFILE_SETTINGS_BY_KEY
from alarm.state_machine.settings import get_setting_json
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from alarm.signals import settings_profile_changed
from alarm.crypto import can_encrypt, encrypt_secret
from integrations_zwavejs.config import (
    normalize_zwavejs_connection,
    prepare_runtime_zwavejs_connection,
)
from integrations_zwavejs.entity_sync import sync_entities_from_zwavejs


zwavejs_gateway = default_zwavejs_gateway
logger = logging.getLogger(__name__)


def _get_profile():
    """Return the active settings profile, creating one if needed."""
    return ensure_active_settings_profile()


def _get_zwavejs_connection_value(profile):
    """Return normalized Z-Wave JS connection settings for the given profile."""
    return normalize_zwavejs_connection(get_setting_json(profile, "zwavejs_connection") or {})


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
        # Some shapes are dict keyed by ints/strings. We just expose keys for filtering.
        command_classes = sorted([str(k) for k in cc_obj.keys()])
    return {
        "node_id": node_id,
        "name": name or label or product_label or (f"Node {node_id}" if node_id else "Unknown node"),
        "manufacturer": manufacturer if isinstance(manufacturer, str) else None,
        "product_label": product_label,
        "command_classes": command_classes,
        "raw": {"id": node_id, "label": label, "productLabel": product_label},
    }


class ZwavejsStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current Z-Wave JS connection status (best-effort applies stored settings)."""
        # Best-effort: apply persisted settings so status reflects reality.
        profile = _get_profile()
        settings_obj = _get_zwavejs_connection_value(profile)
        zwavejs_gateway.apply_settings(settings_obj=prepare_runtime_zwavejs_connection(settings_obj))
        return Response(zwavejs_gateway.get_status().as_dict(), status=status.HTTP_200_OK)


class ZwavejsSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current persisted Z-Wave JS connection settings."""
        profile = _get_profile()
        value = _get_zwavejs_connection_value(profile)
        return Response(ZwavejsConnectionSettingsSerializer(value).data, status=status.HTTP_200_OK)

    def patch(self, request):
        """Update persisted Z-Wave JS settings and apply them to the runtime gateway."""
        profile = _get_profile()
        current = _get_zwavejs_connection_value(profile)
        serializer = ZwavejsConnectionSettingsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)

        if "api_token" in changes:
            if changes.get("api_token") and not can_encrypt():
                raise ValidationError("Encryption is not configured. Set SETTINGS_ENCRYPTION_KEY before saving secrets.")
            changes["api_token"] = encrypt_secret(changes.get("api_token"))
        else:
            # Preserve existing token if not provided.
            changes["api_token"] = current.get("api_token", "")

        merged = dict(current)
        merged.update(changes)

        definition = ALARM_PROFILE_SETTINGS_BY_KEY["zwavejs_connection"]
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="zwavejs_connection",
            defaults={"value": merged, "value_type": definition.value_type},
        )

        # Best-effort: refresh gateway connection state based on stored config.
        zwavejs_gateway.apply_settings(settings_obj=prepare_runtime_zwavejs_connection(merged))

        transaction.on_commit(lambda: settings_profile_changed.send(sender=None, profile_id=profile.id, reason="updated"))
        return Response(ZwavejsConnectionSettingsSerializer(merged).data, status=status.HTTP_200_OK)


class ZwavejsTestConnectionView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Test a Z-Wave JS connection without persisting settings."""
        serializer = ZwavejsTestConnectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.validated_data

        if not settings_obj.get("ws_url"):
            raise ValidationError("Z-Wave JS ws_url is required.")
        zwavejs_gateway.test_connection(settings_obj=settings_obj, timeout_seconds=settings_obj.get("connect_timeout_seconds"))
        return Response({"ok": True}, status=status.HTTP_200_OK)


class ZwavejsEntitySyncView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Sync entities from Z-Wave JS into the local entity registry (admin-only)."""
        profile = _get_profile()
        settings_obj = _get_zwavejs_connection_value(profile)
        if not settings_obj.get("enabled"):
            raise ValidationError("Z-Wave JS is disabled.")
        if not settings_obj.get("ws_url"):
            raise ValidationError("Z-Wave JS ws_url is required.")

        zwavejs_gateway.apply_settings(settings_obj=prepare_runtime_zwavejs_connection(settings_obj))
        zwavejs_gateway.ensure_connected(timeout_seconds=float(settings_obj.get("connect_timeout_seconds") or 5))

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

        profile = _get_profile()
        settings_obj = _get_zwavejs_connection_value(profile)
        if not settings_obj.get("enabled"):
            raise ValidationError("Z-Wave JS is disabled.")
        if not settings_obj.get("ws_url"):
            raise ValidationError("Z-Wave JS ws_url is required.")

        zwavejs_gateway.apply_settings(settings_obj=prepare_runtime_zwavejs_connection(settings_obj))
        zwavejs_gateway.ensure_connected(timeout_seconds=float(settings_obj.get("connect_timeout_seconds") or 5))

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
    """
    Best-effort node listing for UI discovery.
    """

    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return a best-effort list of controller nodes for UI discovery (admin-only)."""
        profile = _get_profile()
        settings_obj = _get_zwavejs_connection_value(profile)
        if not settings_obj.get("enabled"):
            raise ValidationError("Z-Wave JS is disabled.")
        if not settings_obj.get("ws_url"):
            raise ValidationError("Z-Wave JS ws_url is required.")

        zwavejs_gateway.apply_settings(settings_obj=prepare_runtime_zwavejs_connection(settings_obj))
        zwavejs_gateway.ensure_connected(timeout_seconds=float(settings_obj.get("connect_timeout_seconds") or 5))

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
