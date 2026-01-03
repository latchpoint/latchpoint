from __future__ import annotations

from accounts.models import User


def is_admin(user: User) -> bool:
    """Return True if the user has admin privileges (superuser/staff/admin role)."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.role_assignments.filter(role__slug="admin").exists()
