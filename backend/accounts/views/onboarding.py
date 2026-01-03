from __future__ import annotations

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import OnboardingSerializer
from accounts.use_cases import onboarding as onboarding_uc


class OnboardingView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        """Return whether onboarding is required."""
        return Response(
            {"onboarding_required": onboarding_uc.onboarding_required()},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        """Complete onboarding by creating the initial admin user."""
        serializer = OnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        result = onboarding_uc.complete_onboarding(
            email=email,
            password=password,
            timezone_name=settings.TIME_ZONE,
        )
        return Response(result.as_dict(), status=status.HTTP_201_CREATED)
