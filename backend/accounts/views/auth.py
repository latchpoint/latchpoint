from __future__ import annotations

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import LoginSerializer, UserSerializer
from accounts.use_cases import auth as auth_uc


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        """Prime CSRF cookie and return the current token."""
        return Response({"csrfToken": get_token(request)}, status=status.HTTP_200_OK)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        """Authenticate a user and establish a Django session (SPA cookie auth)."""
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        result = auth_uc.login(request=request, email=email, password=password)
        django_login(request._request, result.user)
        return Response(
            {
                "user": UserSerializer(result.user).data,
                "accessToken": result.token.key,
                "refreshToken": result.token.key,
                "requires2FA": False,
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    def post(self, request):
        """End the current session and invalidate any issued compatibility token."""
        user = request.user
        django_logout(request._request)
        if getattr(user, "is_authenticated", False):
            auth_uc.logout(user=user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RefreshTokenView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        """Refresh an access token (legacy compatibility path)."""
        refresh = request.data.get("refresh")
        if not refresh:
            raise ValidationError({"refresh": ["Missing refresh token."]})
        token = auth_uc.refresh_token(refresh=refresh)
        return Response(
            {"accessToken": token.key, "refreshToken": token.key},
            status=status.HTTP_200_OK,
        )
