from __future__ import annotations

from django.urls import path

from integrations_frigate import views


urlpatterns = [
    path("status/", views.FrigateStatusView.as_view(), name="frigate-status"),
    path("settings/", views.FrigateSettingsView.as_view(), name="frigate-settings"),
    path("options/", views.FrigateOptionsView.as_view(), name="frigate-options"),
    path("detections/", views.FrigateDetectionsView.as_view(), name="frigate-detections"),
    path("detections/<int:pk>/", views.FrigateDetectionDetailView.as_view(), name="frigate-detection-detail"),
]
