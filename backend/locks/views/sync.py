from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.gateways.home_assistant import (
    default_home_assistant_gateway,
)

from locks.use_cases import lock_sync

ha_gateway = default_home_assistant_gateway


class AvailableLocksView(APIView):
    """
    Fetch available lock entities from Home Assistant.

    GET /api/locks/available/
    Returns list of lock entities the user can select from.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return available lock entities from Home Assistant (best-effort)."""
        ha_gateway.ensure_available()
        locks = lock_sync.fetch_available_locks(ha_gateway=ha_gateway)
        return Response({"data": locks}, status=status.HTTP_200_OK)
