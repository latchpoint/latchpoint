from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.log_handler import clear_buffer, get_buffered_entries

logger = logging.getLogger(__name__)

_VALID_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class DebugLogsView(APIView):
    """Admin-only endpoint for reading / clearing the in-memory log buffer."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        """Return buffered log entries with optional filtering."""
        level_name = request.query_params.get("level", "").upper()
        level = _VALID_LEVELS.get(level_name)
        logger_name = request.query_params.get("logger") or None

        limit: int | None = None
        limit_raw = request.query_params.get("limit")
        if limit_raw is not None:
            try:
                limit = max(1, int(limit_raw))
            except (ValueError, TypeError):
                pass

        entries = get_buffered_entries(level=level, logger_name=logger_name, limit=limit)
        return Response(entries, status=status.HTTP_200_OK)

    def delete(self, request):
        """Clear the in-memory log buffer."""
        clear_buffer()
        return Response(status=status.HTTP_204_NO_CONTENT)
