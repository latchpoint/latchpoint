from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from alarm.models import AlarmSettingsProfile, AlarmState
from alarm.serializers import (
    AlarmSettingsProfileDetailSerializer,
    AlarmSettingsProfileMetaSerializer,
    AlarmSettingsProfileSerializer,
    AlarmSettingsProfileUpdateSerializer,
)
from alarm.state_machine.timing import resolve_timing
from alarm.use_cases import settings_profile as settings_uc


class AlarmSettingsProfilesView(APIView):
    def get_permissions(self):
        """Allow only admins to create profiles; all authenticated users can list."""
        if getattr(self.request, "method", "").upper() == "POST":
            return [IsAuthenticated(), IsAdminRole()]
        return super().get_permissions()

    def get(self, request):
        """List settings profiles (metadata only)."""
        profiles = settings_uc.list_settings_profiles()
        return Response(AlarmSettingsProfileMetaSerializer(profiles, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a new settings profile (admin-only)."""
        name = (request.data or {}).get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValidationError({"name": ["Name is required."]})
        profile = settings_uc.create_settings_profile(name=name.strip())
        return Response(AlarmSettingsProfileMetaSerializer(profile).data, status=status.HTTP_201_CREATED)


class AlarmSettingsProfileDetailView(APIView):
    def get_permissions(self):
        """Allow only admins to update/delete; all authenticated users can read."""
        method = getattr(self.request, "method", "").upper()
        if method in {"PATCH", "DELETE"}:
            return [IsAuthenticated(), IsAdminRole()]
        return super().get_permissions()

    def get(self, request, profile_id: int):
        """Return full profile details (including entries)."""
        profile = get_object_or_404(AlarmSettingsProfile, id=profile_id)
        return Response(AlarmSettingsProfileDetailSerializer(profile).data, status=status.HTTP_200_OK)

    def patch(self, request, profile_id: int):
        """Update profile metadata and/or entries (admin-only)."""
        profile = get_object_or_404(AlarmSettingsProfile, id=profile_id)
        serializer = AlarmSettingsProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = settings_uc.update_settings_profile(profile=profile, changes=dict(serializer.validated_data))
        return Response(AlarmSettingsProfileDetailSerializer(profile).data, status=status.HTTP_200_OK)

    def delete(self, request, profile_id: int):
        """Delete a settings profile (admin-only; cannot delete active profile)."""
        profile = get_object_or_404(AlarmSettingsProfile, id=profile_id)
        settings_uc.delete_settings_profile(profile=profile)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AlarmSettingsProfileActivateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, profile_id: int):
        """Activate the selected settings profile (admin-only)."""
        profile = get_object_or_404(AlarmSettingsProfile, id=profile_id)
        profile = settings_uc.activate_settings_profile(profile=profile)
        return Response(AlarmSettingsProfileMetaSerializer(profile).data, status=status.HTTP_200_OK)


class AlarmSettingsTimingView(APIView):
    def get(self, request, state: str):
        """Return resolved timing for a target alarm state under the active profile."""
        if state not in set(AlarmState.values):
            raise ValidationError({"state": ["Invalid state."]})

        profile = settings_uc.ensure_active_settings_profile()
        timing = resolve_timing(profile, target_state=state)
        return Response(timing.as_dict(), status=status.HTTP_200_OK)
