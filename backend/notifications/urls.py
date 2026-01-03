"""
URL routing for notification providers API.
"""

from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    # Provider CRUD
    path("providers/", views.ProviderListCreateView.as_view(), name="provider-list"),
    path(
        "providers/<uuid:pk>/", views.ProviderDetailView.as_view(), name="provider-detail"
    ),
    # HA system provider test must come before UUID pattern
    path(
        "providers/ha-system-provider/test/",
        views.TestHaSystemProviderView.as_view(),
        name="ha-system-provider-test",
    ),
    path(
        "providers/<uuid:pk>/test/",
        views.TestProviderView.as_view(),
        name="provider-test",
    ),
    # Provider types metadata
    path("provider-types/", views.ProviderTypesView.as_view(), name="provider-types"),
    # Notification logs
    path("logs/", views.NotificationLogListView.as_view(), name="log-list"),
    # Provider-specific endpoints
    path(
        "pushbullet/devices/",
        views.PushbulletDevicesView.as_view(),
        name="pushbullet-devices",
    ),
    path(
        "pushbullet/validate-token/",
        views.PushbulletValidateTokenView.as_view(),
        name="pushbullet-validate-token",
    ),
    path(
        "home-assistant/services/",
        views.HomeAssistantServicesView.as_view(),
        name="ha-services",
    ),
]
