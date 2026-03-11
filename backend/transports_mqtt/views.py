from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.env_config import get_mqtt_config
from alarm.gateways.mqtt import default_mqtt_gateway
from alarm.serializers import MqttTestConnectionSerializer


mqtt_gateway = default_mqtt_gateway


class MqttStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return current MQTT connection status."""
        status_obj = mqtt_gateway.get_status().as_dict()
        return Response(status_obj, status=status.HTTP_200_OK)


class MqttSettingsView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """Return the current MQTT connection settings from env vars."""
        cfg = get_mqtt_config()
        return Response(
            {
                "enabled": cfg["enabled"],
                "host": cfg["host"],
                "port": cfg["port"],
                "username": cfg["username"],
                "has_password": bool(cfg["password"]),
                "use_tls": cfg["use_tls"],
                "tls_insecure": cfg["tls_insecure"],
                "client_id": cfg["client_id"],
                "keepalive_seconds": cfg["keepalive_seconds"],
                "connect_timeout_seconds": cfg["connect_timeout_seconds"],
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        """MQTT settings are now configured via environment variables."""
        raise MethodNotAllowed(request.method, detail="MQTT settings are configured via environment variables.")


class MqttTestConnectionView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        """Test an MQTT connection without persisting settings."""
        serializer = MqttTestConnectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        settings_obj = serializer.validated_data
        mqtt_gateway.test_connection(settings=settings_obj)
        return Response({"ok": True}, status=status.HTTP_200_OK)
