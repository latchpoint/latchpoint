from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.serializers import AlarmSettingsProfileDetailSerializer
from alarm.use_cases.settings_profile import ensure_active_settings_profile


class AlarmSettingsView(APIView):
    def get(self, request):
        """Return the current active settings profile with entries."""
        profile = ensure_active_settings_profile()
        return Response(AlarmSettingsProfileDetailSerializer(profile).data)
