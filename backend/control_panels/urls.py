from __future__ import annotations

from django.urls import path

from control_panels import views


urlpatterns = [
    path("", views.ControlPanelDeviceListCreateView.as_view(), name="control-panel-device-list-create"),
    path("<int:device_id>/", views.ControlPanelDeviceDetailView.as_view(), name="control-panel-device-detail"),
    path("<int:device_id>/test/", views.ControlPanelDeviceTestView.as_view(), name="control-panel-device-test"),
]
