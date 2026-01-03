from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm import services
from alarm.serializers import AlarmStateSnapshotSerializer
from alarm.use_cases import alarm_actions


class ArmAlarmView(APIView):
    def post(self, request):
        """Arm the alarm, optionally validating an entered code depending on settings."""
        target_state = request.data.get("target_state")
        raw_code = request.data.get("code")
        snapshot = alarm_actions.arm_alarm(
            user=request.user,
            target_state=target_state,
            raw_code=raw_code,
        )
        return Response(AlarmStateSnapshotSerializer(snapshot).data)


class DisarmAlarmView(APIView):
    def post(self, request):
        """Disarm the alarm, validating a code when required."""
        raw_code = request.data.get("code")
        snapshot = alarm_actions.disarm_alarm(user=request.user, raw_code=raw_code)
        return Response(AlarmStateSnapshotSerializer(snapshot).data)


class CancelArmingView(APIView):
    def post(self, request):
        """Cancel an in-progress arming transition."""
        snapshot = services.cancel_arming(user=request.user)
        return Response(AlarmStateSnapshotSerializer(snapshot).data)
