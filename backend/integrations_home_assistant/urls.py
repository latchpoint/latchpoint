from __future__ import annotations

from django.urls import path

from integrations_home_assistant import views

urlpatterns = [
    path("status/", views.HomeAssistantStatusView.as_view(), name="ha-status"),
    path("settings/", views.HomeAssistantSettingsView.as_view(), name="ha-settings"),
    path("entities/", views.HomeAssistantEntitiesView.as_view(), name="ha-entities"),
    path("notify-services/", views.HomeAssistantNotifyServicesView.as_view(), name="ha-notify-services"),
]
