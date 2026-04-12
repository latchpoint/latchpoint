from __future__ import annotations

from dataclasses import dataclass, field

from alarm.models import AlarmState, SystemConfigValueType


def coerce_settings_values(data: dict, config_schema: dict) -> dict:
    """Coerce incoming setting values to the types declared in the config_schema.

    Raises ``ValueError`` for values that cannot be converted (e.g. ``"abc"``
    for an integer field).  Only keys present in *data* are touched; unknown
    keys pass through so the caller can reject them separately.
    """
    properties = config_schema.get("properties", {})
    coerced: dict = {}
    errors: list[str] = []

    for key, value in data.items():
        prop = properties.get(key)
        if prop is None:
            coerced[key] = value
            continue

        declared_type = prop.get("type")
        try:
            if declared_type == "integer":
                if isinstance(value, bool):
                    raise ValueError("boolean is not a valid integer")
                if isinstance(value, float):
                    if not value.is_integer():
                        raise ValueError("non-integral float")
                    coerced[key] = int(value)
                elif not isinstance(value, int):
                    coerced[key] = int(value)
                else:
                    coerced[key] = value
            elif declared_type == "number":
                if isinstance(value, bool):
                    raise ValueError("boolean is not a valid number")
                if not isinstance(value, (int, float)):
                    coerced[key] = float(value)
                else:
                    coerced[key] = value
            elif declared_type == "boolean" and not isinstance(value, bool):
                if isinstance(value, str):
                    coerced[key] = value.lower() in ("true", "1", "yes")
                else:
                    coerced[key] = bool(value)
            else:
                coerced[key] = value
        except (ValueError, TypeError):
            errors.append(f"{key}: expected {declared_type}")

    if errors:
        raise ValueError("; ".join(errors))

    # Enforce minimum / maximum from schema
    for key, value in coerced.items():
        prop = properties.get(key, {})
        if not isinstance(value, (int, float)):
            continue
        minimum = prop.get("minimum")
        maximum = prop.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{key}: must be >= {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{key}: must be <= {maximum}")

    if errors:
        raise ValueError("; ".join(errors))

    return coerced


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
            "request_timeout_seconds": 5,
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
                    "default": "http://localhost:8123",
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
                    "default": 2,
                    "minimum": 1,
                    "maximum": 30,
                    "description": "Maximum time to wait for initial connection",
                },
                "request_timeout_seconds": {
                    "type": "number",
                    "title": "Request Timeout (seconds)",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 60,
                    "description": "Timeout for API requests (entity discovery, service calls)",
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
            "reconnect_min_seconds": 1,
            "reconnect_max_seconds": 120,
        },
        description="MQTT broker connection and operational settings.",
        encrypted_fields=["password"],
        config_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "title": "Enabled"},
                "host": {
                    "type": "string",
                    "title": "Host",
                    "default": "localhost",
                    "description": "MQTT broker hostname or IP address",
                },
                "port": {
                    "type": "integer",
                    "title": "Port",
                    "default": 1883,
                    "minimum": 1,
                    "maximum": 65535,
                    "description": "MQTT broker port",
                },
                "username": {
                    "type": "string",
                    "title": "Username",
                    "description": "Broker username (leave empty if not required)",
                },
                "password": {"type": "string", "title": "Password", "secret": True},
                "use_tls": {
                    "type": "boolean",
                    "title": "Use TLS",
                    "default": False,
                    "description": "Connect to the broker using TLS encryption",
                },
                "tls_insecure": {
                    "type": "boolean",
                    "title": "TLS Insecure (skip verify)",
                    "default": False,
                    "description": "Skip TLS certificate verification (not recommended)",
                },
                "client_id": {
                    "type": "string",
                    "title": "Client ID",
                    "default": "latchpoint-alarm",
                    "description": "MQTT client identifier (must be unique per broker)",
                },
                "keepalive_seconds": {
                    "type": "integer",
                    "title": "Keepalive (seconds)",
                    "default": 30,
                    "minimum": 5,
                    "maximum": 3600,
                    "description": "Interval between keepalive pings to the broker",
                },
                "connect_timeout_seconds": {
                    "type": "integer",
                    "title": "Connect Timeout (seconds)",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 30,
                    "description": "Maximum time to wait for a broker connection",
                },
                "reconnect_min_seconds": {
                    "type": "integer",
                    "title": "Reconnect Min (seconds)",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 60,
                    "description": "Initial delay before reconnecting after a disconnect",
                },
                "reconnect_max_seconds": {
                    "type": "integer",
                    "title": "Reconnect Max (seconds)",
                    "default": 120,
                    "minimum": 5,
                    "maximum": 300,
                    "description": "Maximum delay between reconnection attempts (exponential backoff)",
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
            "request_timeout_seconds": 10,
        },
        description="Z-Wave JS WebSocket connection and operational settings.",
        encrypted_fields=["api_token"],
        config_schema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "title": "Enabled"},
                "ws_url": {
                    "type": "string",
                    "title": "WebSocket URL",
                    "default": "ws://localhost:3000",
                    "format": "uri",
                    "description": "Z-Wave JS Server WebSocket URL",
                },
                "api_token": {"type": "string", "title": "API Token", "secret": True},
                "connect_timeout_seconds": {
                    "type": "integer",
                    "title": "Connect Timeout (seconds)",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 30,
                    "description": "Maximum time to wait for WebSocket connection",
                },
                "reconnect_min_seconds": {
                    "type": "integer",
                    "title": "Reconnect Min (seconds)",
                    "default": 1,
                    "minimum": 1,
                    "maximum": 60,
                    "description": "Initial delay before reconnecting after a disconnect",
                },
                "reconnect_max_seconds": {
                    "type": "integer",
                    "title": "Reconnect Max (seconds)",
                    "default": 30,
                    "minimum": 5,
                    "maximum": 300,
                    "description": "Maximum delay between reconnection attempts (exponential backoff)",
                },
                "request_timeout_seconds": {
                    "type": "integer",
                    "title": "Request Timeout (seconds)",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 60,
                    "description": "Timeout for Z-Wave node operations (value reads, writes, metadata)",
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
