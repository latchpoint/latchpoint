from __future__ import annotations

from django.shortcuts import get_object_or_404


def get_object_or_404_with_perms(*, request, view, queryset, **lookup):
    """
    Fetch an object and enforce DRF object permissions.

    Use with APIView subclasses, since they don't automatically call
    `check_object_permissions()` like DRF generic views.
    """

    obj = get_object_or_404(queryset, **lookup)
    view.check_object_permissions(request, obj)
    return obj


class ObjectPermissionMixin:
    """
    Helper for DRF APIViews that need object-level permissions.

    DRF generic views handle this automatically; APIViews do not.
    """

    def get_object_or_404(self, request, queryset, **lookup):
        """Fetch an object and enforce DRF object permissions."""
        return get_object_or_404_with_perms(request=request, view=self, queryset=queryset, **lookup)
