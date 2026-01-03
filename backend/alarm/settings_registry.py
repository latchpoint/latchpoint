from __future__ import annotations

from dataclasses import dataclass

from alarm.models import AlarmState, SystemConfigValueType


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    name: str
    value_type: str
    default: object
    description: str = ""
    deprecated: bool = False
    deprecation_message: str = ""


ALARM_PROFILE_SETTINGS: list[SettingDefinition] = [
    SettingDefinition(
        key="delay_time",
        name="Delay time",
        value_type=SystemConfigValueType.INTEGER,
        default=60,
        description="Entry delay (seconds) before triggering after a sensor is tripped while armed.",
    ),
    SettingDefinition(
        key="arming_time",
        name="Arming time",
        value_type=SystemConfigValueType.INTEGER,
        default=60,
        description="Exit delay (seconds) before the system becomes armed.",
    ),
    SettingDefinition(
        key="trigger_time",
        name="Trigger time",
        value_type=SystemConfigValueType.INTEGER,
        default=600,
        description="How long (seconds) the alarm remains triggered before auto behavior applies.",
    ),
    SettingDefinition(
        key="disarm_after_trigger",
        name="Disarm after trigger",
        value_type=SystemConfigValueType.BOOLEAN,
        default=False,
        description="If true, auto-disarm after trigger_time; otherwise return to the previous armed state.",
    ),
    SettingDefinition(
        key="code_arm_required",
        name="Code required to arm",
        value_type=SystemConfigValueType.BOOLEAN,
        default=True,
        description="If false, allow arming without a PIN (disarm still requires a code).",
    ),
    SettingDefinition(
        key="available_arming_states",
        name="Available arming states",
        value_type=SystemConfigValueType.JSON,
        default=[
            AlarmState.ARMED_AWAY,
            AlarmState.ARMED_HOME,
            AlarmState.ARMED_NIGHT,
            AlarmState.ARMED_VACATION,
        ],
        description="Restrict which arm modes are available in the UI.",
    ),
    SettingDefinition(
        key="state_overrides",
        name="State overrides",
        value_type=SystemConfigValueType.JSON,
        default={
            AlarmState.ARMED_HOME: {"arming_time": 0},
            AlarmState.ARMED_NIGHT: {"arming_time": 10},
            AlarmState.ARMED_AWAY: {"arming_time": 60},
            AlarmState.ARMED_VACATION: {"arming_time": 60},
        },
        description="Per-state timing overrides (delay_time/arming_time/trigger_time).",
    ),
    SettingDefinition(
        key="audio_visual_settings",
        name="Audio/visual settings",
        value_type=SystemConfigValueType.JSON,
        default={
            "beep_enabled": True,
            "countdown_display_enabled": True,
            "color_coding_enabled": True,
        },
        description="UI feedback toggles and (future) patterns.",
    ),
    SettingDefinition(
        key="sensor_behavior",
        name="Sensor behavior",
        value_type=SystemConfigValueType.JSON,
        default={
            "warn_on_open_sensors": True,
            "auto_bypass_enabled": False,
            "force_arm_enabled": True,
        },
        description="Policies around open sensors at arm time.",
    ),
    SettingDefinition(
        key="home_assistant_connection",
        name="Home Assistant connection",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "base_url": "http://localhost:8123",
            "token": "",
            "connect_timeout_seconds": 2,
        },
        description="Home Assistant URL and long-lived access token (token stored encrypted).",
    ),
    SettingDefinition(
        key="mqtt_connection",
        name="MQTT connection",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "host": "localhost",
            "port": 1883,
            "username": "",
            "password": "",
            "use_tls": False,
            "tls_insecure": False,
            "client_id": "latchpoint-alarm",
            "keepalive_seconds": 30,
            "connect_timeout_seconds": 5,
        },
        description="MQTT broker connection settings used by integrations (Home Assistant, Zigbee2MQTT, etc).",
    ),
    SettingDefinition(
        key="home_assistant_alarm_entity",
        name="Home Assistant alarm entity",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "entity_name": "Latchpoint",
            "also_rename_in_home_assistant": True,
            "ha_entity_id": "alarm_control_panel.latchpoint_alarm",
        },
        description="Home Assistant alarm entity settings (MQTT discovery).",
    ),
    SettingDefinition(
        key="zwavejs_connection",
        name="Z-Wave JS connection",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "ws_url": "ws://localhost:3000",
            "api_token": "",
            "connect_timeout_seconds": 5,
            "reconnect_min_seconds": 1,
            "reconnect_max_seconds": 30,
        },
        description="Z-Wave JS Server connection settings (WebSocket).",
    ),
    SettingDefinition(
        key="zigbee2mqtt",
        name="Zigbee2MQTT",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "base_topic": "zigbee2mqtt",
            "allowlist": [],
            "denylist": [],
            "run_rules_on_event": False,
            "run_rules_debounce_seconds": 2,
            "run_rules_max_per_minute": 30,
            "run_rules_kinds": ["trigger"],
        },
        description="Zigbee2MQTT integration settings (inventory sync, ingest, and rules triggers).",
    ),
    SettingDefinition(
        key="frigate",
        name="Frigate",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "events_topic": "frigate/events",
            "retention_seconds": 3600,
            "run_rules_on_event": True,
            "run_rules_debounce_seconds": 2,
            "run_rules_max_per_minute": 30,
            "run_rules_kinds": ["trigger"],
            "known_cameras": [],
            "known_zones_by_camera": {},
        },
        description="Frigate integration settings (MQTT events ingest for rules conditions).",
    ),
]

ALARM_PROFILE_SETTINGS_BY_KEY = {d.key: d for d in ALARM_PROFILE_SETTINGS}


SYSTEM_CONFIG_SETTINGS: list[SettingDefinition] = [
    SettingDefinition(
        key="events.retention_days",
        name="Event retention (days)",
        value_type=SystemConfigValueType.INTEGER,
        default=30,
        description="How long to keep event history before pruning.",
    ),
    SettingDefinition(
        key="rule_logs.retention_days",
        name="Rule log retention (days)",
        value_type=SystemConfigValueType.INTEGER,
        default=14,
        description="Number of days to retain rule execution logs before automatic cleanup.",
    ),
    SettingDefinition(
        key="entity_sync.interval_seconds",
        name="Entity sync interval (seconds)",
        value_type=SystemConfigValueType.INTEGER,
        default=300,
        description="How often to sync entity states from Home Assistant (0 to disable).",
    ),
]

SYSTEM_CONFIG_SETTINGS_BY_KEY = {d.key: d for d in SYSTEM_CONFIG_SETTINGS}
