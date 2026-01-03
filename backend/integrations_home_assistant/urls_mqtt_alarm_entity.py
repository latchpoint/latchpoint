from __future__ import annotations

from django.urls import path

from integrations_home_assistant import views_mqtt_alarm_entity as views

urlpatterns = [
    path("status/", views.HomeAssistantMqttAlarmEntityStatusView.as_view(), name="integrations-ha-mqtt-alarm-entity-status"),
    path("", views.HomeAssistantMqttAlarmEntitySettingsView.as_view(), name="integrations-ha-mqtt-alarm-entity"),
    path(
        "publish-discovery/",
        views.HomeAssistantMqttAlarmEntityPublishDiscoveryView.as_view(),
        name="integrations-ha-mqtt-alarm-entity-publish-discovery",
    ),
]

