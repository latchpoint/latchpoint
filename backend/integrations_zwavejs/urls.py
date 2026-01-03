from __future__ import annotations

from django.urls import path

from integrations_zwavejs import views

urlpatterns = [
    path("status/", views.ZwavejsStatusView.as_view(), name="zwavejs-status"),
    path("settings/", views.ZwavejsSettingsView.as_view(), name="zwavejs-settings"),
    path("test/", views.ZwavejsTestConnectionView.as_view(), name="zwavejs-test"),
    path("entities/sync/", views.ZwavejsEntitySyncView.as_view(), name="zwavejs-entities-sync"),
    path("set-value/", views.ZwavejsSetValueView.as_view(), name="zwavejs-set-value"),
    path("nodes/", views.ZwavejsNodesView.as_view(), name="zwavejs-nodes"),
]
