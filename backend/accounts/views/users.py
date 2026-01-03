from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from accounts.models import User
from accounts.serializers import UserSerializer
from accounts.use_cases import users as users_uc


class CurrentUserView(APIView):
    def get(self, request):
        """Return the current authenticated user (or anonymous) with common relations prefetched."""
        user = request.user
        if getattr(user, "is_authenticated", False):
            user = users_uc.get_user_for_self(user_id=user.id)
        return Response(UserSerializer(user).data, status=status.HTTP_200_OK)


class UsersView(APIView):
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        """List users (admin-only)."""
        users = users_uc.list_users_for_admin()
        return Response(UserSerializer(users, many=True).data, status=status.HTTP_200_OK)
