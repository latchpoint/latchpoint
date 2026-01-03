from __future__ import annotations

from rest_framework.permissions import BasePermission

from accounts.policies import is_admin


class IsAdminRole(BasePermission):
    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        """Allow access only for admin users."""
        return is_admin(request.user)


class IsAdminOrSelf(BasePermission):
    message = "Forbidden."

    def has_permission(self, request, view) -> bool:
        """Allow access for admins or any authenticated user (object checks apply for non-admins)."""
        if is_admin(request.user):
            return True
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj) -> bool:
        """Allow access for admins or when the object belongs to the requesting user."""
        if is_admin(request.user):
            return True
        owner_id = getattr(obj, "user_id", None) or getattr(obj, "user", None) and getattr(obj.user, "id", None)
        return owner_id == getattr(request.user, "id", None)
