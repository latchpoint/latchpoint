"""API endpoints for the PendingAction queue (ADR-0091).

GET  /api/alarm/pending-actions/?status=scheduled  — list
POST /api/alarm/pending-actions/<id>/cancel/       — manual cancel
"""

from __future__ import annotations

from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.models import PendingAction, PendingActionStatus
from alarm.rules.pending_actions import cancel_by_id
from alarm.serializers import PendingActionSerializer


class PendingActionsListView(APIView):
    """List queued / recently-fired / cancelled actions.

    Query params:
      - ``status`` (optional): filter by status (default: ``scheduled``).
        Pass ``all`` to include every status.
      - ``limit`` (optional, default 100, max 500): page size.
    """

    def get(self, request):
        status_filter = request.query_params.get("status", PendingActionStatus.SCHEDULED)
        try:
            limit = min(int(request.query_params.get("limit", 100)), 500)
        except (TypeError, ValueError):
            limit = 100

        qs = PendingAction.objects.select_related("rule", "actor_user").order_by("-fire_at", "-id")
        if status_filter != "all":
            qs = qs.filter(status=status_filter)
        rows = list(qs[:limit])
        return Response(PendingActionSerializer(rows, many=True).data)


class PendingActionCancelView(APIView):
    """Manually cancel a queued action."""

    def post(self, request, pending_action_id: int):
        cancelled = cancel_by_id(pending_action_id)
        if not cancelled:
            return Response(
                {"detail": "Pending action not found or already in a terminal state."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        pa = PendingAction.objects.select_related("rule", "actor_user").get(id=pending_action_id)
        return Response(PendingActionSerializer(pa).data)
