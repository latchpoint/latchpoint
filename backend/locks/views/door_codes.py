from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from config.view_utils import ObjectPermissionMixin
from locks.models import DoorCode
from locks.permissions import IsAdminOrSelf, IsAdminRole
from locks.serializers import (
    DoorCodeCreateSerializer,
    DoorCodeSerializer,
    DoorCodeUpdateSerializer,
)
from locks.use_cases import door_codes as door_codes_uc


class DoorCodesView(APIView):
    def get_permissions(self):
        """Allow only admins to create door codes; all authenticated users can list."""
        if getattr(self.request, "method", "").upper() == "POST":
            return [IsAuthenticated(), IsAdminRole()]
        return super().get_permissions()

    def get(self, request):
        """List door codes for the current user (or another user when admin + user_id)."""
        user_id = request.query_params.get("user_id")
        target_user = door_codes_uc.resolve_list_target_user(
            actor_user=request.user, requested_user_id=user_id
        )
        codes = door_codes_uc.list_door_codes_for_user(user=target_user)
        return Response(DoorCodeSerializer(codes, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a door code for a target user (admin-only, requires re-auth)."""
        reauth_password = request.data.get("reauth_password")
        door_codes_uc.assert_admin_reauth(user=request.user, reauth_password=reauth_password)
        target_user = door_codes_uc.resolve_create_target_user(
            actor_user=request.user,
            requested_user_id=request.data.get("user_id"),
        )

        serializer = DoorCodeCreateSerializer(
            data=request.data,
            context={"request": request, "target_user": target_user},
        )
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)
        validated.pop("reauth_password", None)
        validated.pop("user_id", None)

        code = door_codes_uc.create_door_code(
            user=target_user,
            raw_code=validated["code"],
            label=validated.get("label", ""),
            code_type=validated.get("code_type", DoorCode.CodeType.PERMANENT),
            start_at=validated.get("start_at"),
            end_at=validated.get("end_at"),
            days_of_week=validated.get("days_of_week"),
            window_start=validated.get("window_start"),
            window_end=validated.get("window_end"),
            max_uses=validated.get("max_uses"),
            lock_entity_ids=validated.get("lock_entity_ids"),
            actor_user=request.user,
        )
        code = (
            DoorCode.objects.select_related("user")
            .prefetch_related("lock_assignments")
            .get(id=code.id)
        )
        return Response(DoorCodeSerializer(code).data, status=status.HTTP_201_CREATED)


class DoorCodeDetailView(ObjectPermissionMixin, APIView):
    def get_permissions(self):
        """Enforce per-method permissions (admins can edit; owners can view)."""
        method = getattr(self.request, "method", "").upper()
        if method in ("PATCH", "DELETE"):
            return [IsAuthenticated(), IsAdminRole()]
        if method == "GET":
            return [IsAuthenticated(), IsAdminOrSelf()]
        return super().get_permissions()

    def get(self, request, code_id: int):
        """Return a single door code (admin or owner)."""
        code = self.get_object_or_404(
            request=request,
            queryset=DoorCode.objects.select_related("user").prefetch_related("lock_assignments"),
            id=code_id,
        )
        return Response(DoorCodeSerializer(code).data, status=status.HTTP_200_OK)

    def patch(self, request, code_id: int):
        """Update a door code (admin-only, requires re-auth)."""
        reauth_password = request.data.get("reauth_password")
        door_codes_uc.assert_admin_reauth(user=request.user, reauth_password=reauth_password)
        code = door_codes_uc.get_door_code_for_admin_update(actor_user=request.user, code_id=code_id)

        serializer = DoorCodeUpdateSerializer(instance=code, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        changes.pop("reauth_password", None)

        code = door_codes_uc.update_door_code(code=code, changes=changes, actor_user=request.user)
        code = (
            DoorCode.objects.select_related("user")
            .prefetch_related("lock_assignments")
            .get(id=code.id)
        )
        return Response(DoorCodeSerializer(code).data, status=status.HTTP_200_OK)

    def delete(self, request, code_id: int):
        """Delete a door code (admin-only, requires re-auth)."""
        reauth_password = request.data.get("reauth_password")
        door_codes_uc.assert_admin_reauth(user=request.user, reauth_password=reauth_password)
        code = door_codes_uc.get_door_code_for_admin_update(actor_user=request.user, code_id=code_id)

        door_codes_uc.delete_door_code(code=code, actor_user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
