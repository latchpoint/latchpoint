from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class SystemTimeView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        now = timezone.now()
        local = timezone.localtime(now)
        return Response(
            {
                "timestamp": now.isoformat(),
                "timezone": settings.TIME_ZONE,
                "epochMs": int(now.timestamp() * 1000),
                "formatted": local.strftime("%Y-%m-%d %H:%M:%S %Z"),
            },
            status=status.HTTP_200_OK,
        )
