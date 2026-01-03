from __future__ import annotations

from django.urls import path

from locks.views import door_codes as views
from locks.views import sync as sync_views

urlpatterns = [
    path("locks/available/", sync_views.AvailableLocksView.as_view(), name="locks-available"),
    path("door-codes/", views.DoorCodesView.as_view(), name="door-codes"),
    path("door-codes/<int:code_id>/", views.DoorCodeDetailView.as_view(), name="door-code-detail"),
]
