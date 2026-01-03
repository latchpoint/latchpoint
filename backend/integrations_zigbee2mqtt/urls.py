from __future__ import annotations

from django.urls import path

from integrations_zigbee2mqtt import views

urlpatterns = [
    path("status/", views.Zigbee2mqttStatusView.as_view(), name="zigbee2mqtt-status"),
    path("settings/", views.Zigbee2mqttSettingsView.as_view(), name="zigbee2mqtt-settings"),
    path("devices/", views.Zigbee2mqttDevicesView.as_view(), name="zigbee2mqtt-devices"),
    path("devices/sync/", views.Zigbee2mqttDevicesSyncView.as_view(), name="zigbee2mqtt-devices-sync"),
]

