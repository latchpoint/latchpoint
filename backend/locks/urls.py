from __future__ import annotations

from django.urls import path

from locks.views import door_codes as views
from locks.views import sync as sync_views
from locks.views import lock_config_sync as lock_config_sync_views

urlpatterns = [
    path("locks/available/", sync_views.AvailableLocksView.as_view(), name="locks-available"),
    path(
        "locks/<path:lock_entity_id>/sync-config/",
        lock_config_sync_views.LockConfigSyncView.as_view(),
        name="locks-sync-config",
    ),
    path("door-codes/", views.DoorCodesView.as_view(), name="door-codes"),
    path("door-codes/<int:code_id>/", views.DoorCodeDetailView.as_view(), name="door-code-detail"),
]
