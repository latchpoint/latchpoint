from __future__ import annotations

from dataclasses import dataclass, field

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
    encrypted_fields: list[str] = field(default_factory=list)
    config_schema: dict | None = None


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
        key="zigbee2mqtt",
        name="Zigbee2MQTT",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "base_topic": "zigbee2mqtt",
            "allowlist": [],
            "denylist": [],
        },
        description="Zigbee2MQTT integration settings (inventory sync and ingest).",
        config_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "title": "Enabled"},
                "base_topic": {
                    "type": "string",
                    "title": "Base Topic",
                    "description": "MQTT base topic for Zigbee2MQTT",
                },
                "allowlist": {
                    "type": "array",
                    "title": "Allowlist",
                    "items": {"type": "string"},
                    "description": "Only sync these friendly names (empty = sync all)",
                },
                "denylist": {
                    "type": "array",
                    "title": "Denylist",
                    "items": {"type": "string"},
                    "description": "Exclude these friendly names from sync",
                },
            },
        },
    ),
    SettingDefinition(
        key="frigate",
        name="Frigate",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "events_topic": "frigate/events",
            "retention_seconds": 3600,
            "known_cameras": [],
            "known_zones_by_camera": {},
        },
        description="Frigate integration settings (MQTT events ingest for rules conditions).",
        config_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "title": "Enabled"},
                "events_topic": {
                    "type": "string",
                    "title": "Events Topic",
                    "description": "MQTT topic for Frigate detection events",
                },
                "retention_seconds": {
                    "type": "integer",
                    "title": "Retention (seconds)",
                    "minimum": 0,
                    "description": "How long to keep Frigate events before pruning",
                },
                "known_cameras": {
                    "type": "array",
                    "title": "Known Cameras",
                    "items": {"type": "string"},
                    "description": "Camera names discovered from Frigate events",
                },
                "known_zones_by_camera": {
                    "type": "object",
                    "title": "Known Zones by Camera",
                    "additionalProperties": {"type": "array", "items": {"type": "string"}},
                    "description": "Zone names per camera discovered from Frigate events",
                },
            },
        },
    ),
    SettingDefinition(
        key="home_assistant",
        name="Home Assistant",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "base_url": "http://localhost:8123",
            "token": "",
            "connect_timeout_seconds": 2,
        },
        description="Home Assistant connection and operational settings.",
        encrypted_fields=["token"],
        config_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "title": "Enabled"},
                "base_url": {
                    "type": "string",
                    "title": "Base URL",
                    "format": "url",
                    "description": "Home Assistant instance URL",
                },
                "token": {
                    "type": "string",
                    "title": "Long-Lived Access Token",
                    "secret": True,
                    "description": "Generate at Profile > Security > Long-lived access tokens",
                },
                "connect_timeout_seconds": {
                    "type": "number",
                    "title": "Connect Timeout (seconds)",
                    "minimum": 1,
                    "maximum": 30,
                },
            },
        },
    ),
    SettingDefinition(
        key="mqtt",
        name="MQTT",
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
        description="MQTT broker connection and operational settings.",
        encrypted_fields=["password"],
        config_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "title": "Enabled"},
                "host": {"type": "string", "title": "Host"},
                "port": {"type": "integer", "title": "Port", "minimum": 1, "maximum": 65535},
                "username": {"type": "string", "title": "Username"},
                "password": {"type": "string", "title": "Password", "secret": True},
                "use_tls": {"type": "boolean", "title": "Use TLS"},
                "tls_insecure": {"type": "boolean", "title": "TLS Insecure (skip verify)"},
                "client_id": {"type": "string", "title": "Client ID"},
                "keepalive_seconds": {"type": "integer", "title": "Keepalive (seconds)", "minimum": 5},
                "connect_timeout_seconds": {
                    "type": "integer",
                    "title": "Connect Timeout (seconds)",
                    "minimum": 1,
                },
            },
        },
    ),
    SettingDefinition(
        key="zwavejs",
        name="Z-Wave JS",
        value_type=SystemConfigValueType.JSON,
        default={
            "enabled": False,
            "ws_url": "ws://localhost:3000",
            "api_token": "",
            "connect_timeout_seconds": 5,
            "reconnect_min_seconds": 1,
            "reconnect_max_seconds": 30,
        },
        description="Z-Wave JS WebSocket connection and operational settings.",
        encrypted_fields=["api_token"],
        config_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "title": "Enabled"},
                "ws_url": {"type": "string", "title": "WebSocket URL", "format": "uri"},
                "api_token": {"type": "string", "title": "API Token", "secret": True},
                "connect_timeout_seconds": {
                    "type": "integer",
                    "title": "Connect Timeout (seconds)",
                    "minimum": 1,
                },
                "reconnect_min_seconds": {
                    "type": "integer",
                    "title": "Reconnect Min (seconds)",
                    "minimum": 1,
                },
                "reconnect_max_seconds": {
                    "type": "integer",
                    "title": "Reconnect Max (seconds)",
                    "minimum": 1,
                },
            },
        },
    ),
]

ALARM_PROFILE_SETTINGS_BY_KEY = {d.key: d for d in ALARM_PROFILE_SETTINGS}


SYSTEM_CONFIG_SETTINGS: list[SettingDefinition] = [
    SettingDefinition(
        key="events.retention_days",
        name="Event retention (days)",
        value_type=SystemConfigValueType.INTEGER,
        default=30,
        description="How long to keep event history before pruning (<= 0 disables cleanup).",
    ),
    SettingDefinition(
        key="notification_logs.retention_days",
        name="Notification log retention (days)",
        value_type=SystemConfigValueType.INTEGER,
        default=30,
        description="How long to keep notification audit logs before pruning (<= 0 disables cleanup).",
    ),
    SettingDefinition(
        key="notification_deliveries.retention_days",
        name="Notification delivery retention (days)",
        value_type=SystemConfigValueType.INTEGER,
        default=30,
        description="How long to keep sent/dead notification deliveries before pruning (<= 0 disables cleanup).",
    ),
    SettingDefinition(
        key="door_code_events.retention_days",
        name="Door code event retention (days)",
        value_type=SystemConfigValueType.INTEGER,
        default=90,
        description="How long to keep door code audit events before pruning (<= 0 disables cleanup).",
    ),
    SettingDefinition(
        key="rule_logs.retention_days",
        name="Rule log retention (days)",
        value_type=SystemConfigValueType.INTEGER,
        default=14,
        description="Number of days to retain rule execution logs before automatic cleanup (<= 0 disables cleanup).",
    ),
    SettingDefinition(
        key="entity_sync.interval_seconds",
        name="Entity sync interval (seconds)",
        value_type=SystemConfigValueType.INTEGER,
        default=300,
        description="How often to sync entity states from Home Assistant (0 to disable).",
    ),
    SettingDefinition(
        key="dispatcher",
        name="Rule trigger dispatcher",
        value_type=SystemConfigValueType.JSON,
        default={
            "debounce_ms": 200,
            "batch_size_limit": 100,
            "rate_limit_per_sec": 10,
            "rate_limit_burst": 50,
            "worker_concurrency": 4,
            "queue_max_depth": 1000,
        },
        description="Centralized rule trigger dispatcher settings (ADR 0057). "
        "Dispatcher is always enabled - these are tuning parameters.",
    ),
]

SYSTEM_CONFIG_SETTINGS_BY_KEY = {d.key: d for d in SYSTEM_CONFIG_SETTINGS}
