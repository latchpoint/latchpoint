from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.models import Role, User, UserRoleAssignment
from config.domain_exceptions import ConflictError, DomainError


class OnboardingError(DomainError):
    pass


class OnboardingAlreadyCompleted(ConflictError):
    pass


def onboarding_required() -> bool:
    """Return True if the system has no users and needs initial onboarding."""
    # Onboarding is only responsible for creating the initial admin user.
    # Everything else can be configured later via the Settings page.
    return not User.objects.exists()


@dataclass(frozen=True)
class OnboardingResult:
    user: User

    def as_dict(self) -> dict[str, str]:
        """Serialize onboarding result to a JSON-friendly dict."""
        return {
            "user_id": str(self.user.id),
            "email": self.user.email,
        }


def complete_onboarding(*, email: str, password: str, timezone_name: str) -> OnboardingResult:
    """Create the initial admin user and assign the admin role (idempotent)."""
    if not onboarding_required():
        raise OnboardingAlreadyCompleted("Onboarding is already completed.")

    with transaction.atomic():
        if not onboarding_required():
            raise OnboardingAlreadyCompleted("Onboarding is already completed.")

        user = User.objects.create_superuser(
            email=email,
            password=password,
            timezone=timezone_name,
            onboarding_completed_at=timezone.now(),
        )
        role, _ = Role.objects.get_or_create(
            slug="admin",
            defaults={
                "name": "Admin",
                "description": "Full administrative access",
            },
        )
        UserRoleAssignment.objects.get_or_create(
            user=user,
            role=role,
            defaults={"assigned_by": user},
        )

    return OnboardingResult(user=user)
