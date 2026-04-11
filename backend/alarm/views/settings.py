from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from alarm.serializers import AlarmSettingsProfileDetailSerializer
from alarm.settings_registry import ALARM_PROFILE_SETTINGS
from alarm.use_cases.settings_profile import ensure_active_settings_profile


class AlarmSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return the current active settings profile with entries."""
        profile = ensure_active_settings_profile()
        return Response(AlarmSettingsProfileDetailSerializer(profile).data)


class SettingsRegistryView(APIView):
    """Expose settings registry metadata for schema-driven frontend forms."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return config_schema and encrypted_fields for all integration settings."""
        entries = []
        for definition in ALARM_PROFILE_SETTINGS:
            if definition.config_schema is None:
                continue
            entries.append(
                {
                    "key": definition.key,
                    "name": definition.name,
                    "description": definition.description,
                    "config_schema": definition.config_schema,
                    "encrypted_fields": definition.encrypted_fields,
                }
            )
        return Response(entries)
