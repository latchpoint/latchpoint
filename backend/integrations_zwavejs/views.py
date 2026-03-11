from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from config.domain_exceptions import ServiceUnavailableError, ValidationError
from alarm.env_config import get_zwavejs_config
from alarm.gateways.zwavejs import default_zwavejs_gateway
from alarm.serializers import ZwavejsSetValueSerializer, ZwavejsTestConnectionSerializer
from integrations_zwavejs.entity_sync import sync_entities_from_zwavejs


zwavejs_gateway = default_zwavejs_gateway
logger = logging.getLogger(__name__)


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
        command_classes = sorted([str(k) for k in cc_obj.keys()])
    return {
        "node_id": node_id,
        "name": name or label or product_label or (f"Node {node_id}" if node_id else "Unknown node"),
        "manufacturer": manufacturer if isinstance(manufacturer, str) else None,
        "product_label": product_label,
        "command_classes": command_classes,
        "raw": {"id": node_id, "label": label, "productLabel": product_label},
    }


def _ensure_zwavejs_ready(cfg: dict) -> None:
    """Apply env config and ensure gateway is connected."""
    if not cfg.get("enabled"):
        raise ValidationError("Z-Wave JS is disabled.")
    if not cfg.get("ws_url"):
        raise ValidationError("Z-Wave JS ws_url is required.")
    zwavejs_gateway.apply_settings(settings_obj=cfg)
    zwavejs_gateway.ensure_connected(timeout_seconds=float(cfg.get("connect_timeout_seconds") or 5))


class ZwavejsStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current Z-Wave JS connection status."""
        return Response(zwavejs_gateway.get_status().as_dict(), status=status.HTTP_200_OK)


class ZwavejsSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current Z-Wave JS connection settings from env vars."""
        cfg = get_zwavejs_config()
        return Response(
            {
                "enabled": cfg["enabled"],
                "ws_url": cfg["ws_url"],
                "has_api_token": bool(cfg["api_token"]),
                "connect_timeout_seconds": cfg["connect_timeout_seconds"],
                "reconnect_min_seconds": cfg["reconnect_min_seconds"],
                "reconnect_max_seconds": cfg["reconnect_max_seconds"],
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        """Z-Wave JS settings are now configured via environment variables."""
        raise MethodNotAllowed(request.method, detail="Z-Wave JS settings are configured via environment variables.")


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
        cfg = get_zwavejs_config()
        _ensure_zwavejs_ready(cfg)

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

        cfg = get_zwavejs_config()
        _ensure_zwavejs_ready(cfg)

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
        cfg = get_zwavejs_config()
        _ensure_zwavejs_ready(cfg)

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
