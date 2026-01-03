from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.models import SystemConfig
from alarm.serializers import SystemConfigSerializer, SystemConfigUpdateSerializer
from alarm.use_cases import system_config as system_config_uc


class SystemConfigListView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """List system config rows (admin-only)."""
        rows = system_config_uc.list_system_config()
        return Response(SystemConfigSerializer(rows, many=True).data, status=status.HTTP_200_OK)


class SystemConfigDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def patch(self, request, key: str):
        """Update a system config row (admin-only)."""
        row = get_object_or_404(SystemConfig, key=key)
        serializer = SystemConfigUpdateSerializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = system_config_uc.update_system_config(row=row, changes=dict(serializer.validated_data), actor_user=request.user)
        return Response(SystemConfigSerializer(row).data, status=status.HTTP_200_OK)
