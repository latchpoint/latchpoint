from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

from alarm import views as alarm_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/alarm/", include("alarm.urls")),
    path("api/control-panels/", include("control_panels.urls")),
    path("api/alarm/mqtt/", include("transports_mqtt.urls")),
    path("api/alarm/zwavejs/", include("integrations_zwavejs.urls")),
    path("api/alarm/home-assistant/", include("integrations_home_assistant.urls")),
    path(
        "api/alarm/integrations/home-assistant/mqtt-alarm-entity/",
        include("integrations_home_assistant.urls_mqtt_alarm_entity"),
    ),
    path("api/alarm/integrations/zigbee2mqtt/", include("integrations_zigbee2mqtt.urls")),
    path("api/alarm/integrations/frigate/", include("integrations_frigate.urls")),
    path("api/notifications/", include("notifications.urls")),
    path("api/events/", alarm_views.AlarmEventsView.as_view(), name="events"),
    path("api/system-config/", alarm_views.SystemConfigListView.as_view(), name="system-config-list"),
    path("api/system-config/<str:key>/", alarm_views.SystemConfigDetailView.as_view(), name="system-config-detail"),
    path("api/scheduler/", include("scheduler.urls")),
    path("api/", include("accounts.urls")),
    path("api/", include("locks.urls")),
]
