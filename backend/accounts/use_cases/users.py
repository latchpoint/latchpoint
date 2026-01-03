from __future__ import annotations

from django.db.models import QuerySet

from accounts.models import User


def get_user_for_self(*, user_id) -> User:
    """Fetch a user for the current session with common relations prefetched."""
    return (
        User.objects.filter(id=user_id)
        .prefetch_related(
            "role_assignments__role",
            "totp_devices",
        )
        .get()
    )


def list_users_for_admin() -> QuerySet[User]:
    """Return a queryset of all users for admin listing with common relations prefetched."""
    return User.objects.order_by("email").prefetch_related(
        "role_assignments__role",
        "totp_devices",
    )
