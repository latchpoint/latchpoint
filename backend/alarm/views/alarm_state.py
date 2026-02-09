from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.serializers import AlarmStateSnapshotSerializer
from alarm.state_machine.transitions import get_current_snapshot


class AlarmStateView(APIView):
    def get(self, request):
        """Return the current alarm state snapshot (processing timers)."""
        snapshot = get_current_snapshot(process_timers=True)
        return Response(AlarmStateSnapshotSerializer(snapshot).data)
