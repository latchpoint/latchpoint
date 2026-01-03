from __future__ import annotations

from django.urls import path

from transports_mqtt import views

urlpatterns = [
    path("status/", views.MqttStatusView.as_view(), name="mqtt-status"),
    path("settings/", views.MqttSettingsView.as_view(), name="mqtt-settings"),
    path("test/", views.MqttTestConnectionView.as_view(), name="mqtt-test"),
]

