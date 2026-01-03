from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.use_cases.setup_status import compute_setup_status


class SetupStatusView(APIView):
    def get(self, request):
        """Return setup requirements/status for the current user."""
        return Response(compute_setup_status(user=request.user), status=status.HTTP_200_OK)
