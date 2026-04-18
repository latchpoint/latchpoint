from __future__ import annotations

from .alarm_state import AlarmStateView
from .debug_logs import DebugLogsView
from .dispatcher import DispatcherConfigView, DispatcherStatusView, SuspendedRulesView
from .entities import EntitiesView, EntitySyncView
from .events import AlarmEventsView
from .rules import (
    RuleDetailView,
    RuleRunView,
    RuleSimulateView,
    RuleStopGroupsView,
    RulesView,
    SupportedActionsView,
)
from .sensors import SensorDetailView, SensorsView
from .settings import AlarmSettingsView, SettingsRegistryView
from .settings_profiles import (
    AlarmSettingsProfileActivateView,
    AlarmSettingsProfileDetailView,
    AlarmSettingsProfilesView,
    AlarmSettingsTimingView,
)
from .system_config import SystemConfigDetailView, SystemConfigListView
from .transitions import ArmAlarmView, CancelArmingView, DisarmAlarmView

__all__ = [
    "DebugLogsView",
    "AlarmSettingsView",
    "AlarmSettingsProfileActivateView",
    "AlarmSettingsProfileDetailView",
    "AlarmSettingsProfilesView",
    "AlarmSettingsTimingView",
    "AlarmStateView",
    "AlarmEventsView",
    "ArmAlarmView",
    "CancelArmingView",
    "DisarmAlarmView",
    "EntitiesView",
    "EntitySyncView",
    "RuleDetailView",
    "RuleRunView",
    "RuleSimulateView",
    "RulesView",
    "RuleStopGroupsView",
    "SupportedActionsView",
    "SensorDetailView",
    "SensorsView",
    "SystemConfigDetailView",
    "SystemConfigListView",
    "DispatcherConfigView",
    "DispatcherStatusView",
    "SettingsRegistryView",
    "SuspendedRulesView",
]
