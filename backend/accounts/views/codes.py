from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserCode
from accounts.permissions import IsAdminOrSelf, IsAdminRole
from accounts.serializers import UserCodeCreateSerializer, UserCodeSerializer, UserCodeUpdateSerializer
from accounts.use_cases import codes as codes_uc
from accounts.use_cases import user_codes as user_codes_uc
from config.view_utils import ObjectPermissionMixin


class CodesView(APIView):
    def get_permissions(self):
        """Allow only admins to create codes; all authenticated users can list."""
        if getattr(self.request, "method", "").upper() == "POST":
            return [IsAuthenticated(), IsAdminRole()]
        return super().get_permissions()

    def get(self, request):
        """List codes for the current user (or another user when admin + user_id)."""
        user_id = request.query_params.get("user_id")
        target_user = codes_uc.resolve_list_target_user(actor_user=request.user, requested_user_id=user_id)
        codes = codes_uc.list_codes_for_user(user=target_user)
        return Response(UserCodeSerializer(codes, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        """Create a code for a target user (admin-only, requires re-auth)."""
        reauth_password = request.data.get("reauth_password")
        codes_uc.assert_admin_reauth(user=request.user, reauth_password=reauth_password)
        target_user = codes_uc.resolve_create_target_user(
            actor_user=request.user,
            requested_user_id=request.data.get("user_id"),
        )

        serializer = UserCodeCreateSerializer(
            data=request.data,
            context={"request": request, "target_user": target_user},
        )
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)
        validated.pop("reauth_password", None)
        validated.pop("user_id", None)
        code = user_codes_uc.create_user_code(
            user=target_user,
            raw_code=validated["code"],
            label=validated.get("label", ""),
            code_type=validated.get("code_type", UserCode.CodeType.PERMANENT),
            start_at=validated.get("start_at"),
            end_at=validated.get("end_at"),
            days_of_week=validated.get("days_of_week"),
            window_start=validated.get("window_start"),
            window_end=validated.get("window_end"),
            allowed_states=validated.get("allowed_states"),
        )
        code = (
            UserCode.objects.select_related("user")
            .prefetch_related("allowed_states")
            .get(id=code.id)
        )
        return Response(UserCodeSerializer(code).data, status=status.HTTP_201_CREATED)


class CodeDetailView(ObjectPermissionMixin, APIView):
    def get_permissions(self):
        """Enforce per-method permissions (admins can edit; owners can view)."""
        method = getattr(self.request, "method", "").upper()
        if method == "PATCH":
            return [IsAuthenticated(), IsAdminRole()]
        if method == "GET":
            return [IsAuthenticated(), IsAdminOrSelf()]
        return super().get_permissions()

    def get(self, request, code_id: int):
        """Return a single code (admin or owner)."""
        code = self.get_object_or_404(
            request=request,
            queryset=UserCode.objects.select_related("user").prefetch_related("allowed_states"),
            id=code_id,
        )
        return Response(UserCodeSerializer(code).data, status=status.HTTP_200_OK)

    def patch(self, request, code_id: int):
        """Update a code (admin-only, requires re-auth)."""
        reauth_password = request.data.get("reauth_password")
        codes_uc.assert_admin_reauth(user=request.user, reauth_password=reauth_password)
        code = codes_uc.get_code_for_admin_update(actor_user=request.user, code_id=code_id)

        serializer = UserCodeUpdateSerializer(instance=code, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = dict(serializer.validated_data)
        changes.pop("reauth_password", None)
        code = user_codes_uc.update_user_code(code=code, changes=changes)
        code = (
            UserCode.objects.select_related("user")
            .prefetch_related("allowed_states")
            .get(id=code.id)
        )
        return Response(UserCodeSerializer(code).data, status=status.HTTP_200_OK)
