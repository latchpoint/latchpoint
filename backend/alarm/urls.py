from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("state/", views.AlarmStateView.as_view(), name="alarm-state"),
    path("entities/", views.EntitiesView.as_view(), name="alarm-entities"),
    path("entities/sync/", views.EntitySyncView.as_view(), name="alarm-entities-sync"),
    path("settings/", views.AlarmSettingsView.as_view(), name="alarm-settings"),
    path("settings/profiles/", views.AlarmSettingsProfilesView.as_view(), name="alarm-settings-profiles"),
    path(
        "settings/profiles/<int:profile_id>/",
        views.AlarmSettingsProfileDetailView.as_view(),
        name="alarm-settings-profile-detail",
    ),
    path(
        "settings/profiles/<int:profile_id>/activate/",
        views.AlarmSettingsProfileActivateView.as_view(),
        name="alarm-settings-profile-activate",
    ),
    path("settings/timing/<str:state>/", views.AlarmSettingsTimingView.as_view(), name="alarm-settings-timing"),
    path("sensors/", views.SensorsView.as_view(), name="alarm-sensors"),
    path("sensors/<int:sensor_id>/", views.SensorDetailView.as_view(), name="alarm-sensor-detail"),
    path("rules/", views.RulesView.as_view(), name="alarm-rules"),
    path("rules/<int:rule_id>/", views.RuleDetailView.as_view(), name="alarm-rule-detail"),
    path("rules/run/", views.RuleRunView.as_view(), name="alarm-rules-run"),
    path("rules/simulate/", views.RuleSimulateView.as_view(), name="alarm-rules-simulate"),
    path("rules/supported-actions/", views.SupportedActionsView.as_view(), name="alarm-rules-supported-actions"),
    path("arm/", views.ArmAlarmView.as_view(), name="alarm-arm"),
    path("disarm/", views.DisarmAlarmView.as_view(), name="alarm-disarm"),
    path("cancel-arming/", views.CancelArmingView.as_view(), name="alarm-cancel-arming"),
    # Debug endpoints (ADR 0072)
    path("debug/logs/", views.DebugLogsView.as_view(), name="debug-logs"),
    # Dispatcher endpoints (ADR 0057)
    path("dispatcher/status/", views.DispatcherStatusView.as_view(), name="dispatcher-status"),
    path("dispatcher/config/", views.DispatcherConfigView.as_view(), name="dispatcher-config"),
    path("dispatcher/suspended-rules/", views.SuspendedRulesView.as_view(), name="dispatcher-suspended-rules"),
]
