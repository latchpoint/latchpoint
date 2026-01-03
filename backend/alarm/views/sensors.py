from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway
from alarm.models import Sensor
from alarm.serializers import SensorCreateSerializer, SensorSerializer, SensorUpdateSerializer
from alarm.use_cases.sensor_context import sensor_detail_serializer_context, sensor_list_serializer_context
from config.view_utils import ObjectPermissionMixin

ha_gateway: HomeAssistantGateway = default_home_assistant_gateway


class SensorsView(APIView):
    def get(self, request):
        """List sensors with serializer context (entity state + last triggered + rule usage)."""
        sensors = list(Sensor.objects.all())
        context = sensor_list_serializer_context(
            sensors=sensors,
            prefer_home_assistant_live_state=True,
            ha_gateway=ha_gateway,
        )
        return Response(SensorSerializer(sensors, many=True, context=context).data)

    def post(self, request):
        """Create a new sensor."""
        serializer = SensorCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sensor = serializer.save()
        return Response(SensorSerializer(sensor).data, status=status.HTTP_201_CREATED)


class SensorDetailView(ObjectPermissionMixin, APIView):
    def get(self, request, sensor_id: int):
        """Return a single sensor with serializer context (including live entity state when available)."""
        sensor = self.get_object_or_404(request, queryset=Sensor.objects.all(), pk=sensor_id)
        context = sensor_detail_serializer_context(
            sensor=sensor,
            prefer_home_assistant_live_state=True,
            ha_gateway=ha_gateway,
        )
        return Response(SensorSerializer(sensor, context=context).data)

    def patch(self, request, sensor_id: int):
        """Partially update a sensor and return refreshed serializer context."""
        sensor = self.get_object_or_404(request, queryset=Sensor.objects.all(), pk=sensor_id)
        serializer = SensorUpdateSerializer(sensor, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        sensor = serializer.save()
        context = sensor_detail_serializer_context(
            sensor=sensor,
            prefer_home_assistant_live_state=False,
            ha_gateway=ha_gateway,
        )
        return Response(SensorSerializer(sensor, context=context).data, status=status.HTTP_200_OK)

    def delete(self, request, sensor_id: int):
        """Delete a sensor."""
        sensor = self.get_object_or_404(request, queryset=Sensor.objects.all(), pk=sensor_id)
        sensor.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
