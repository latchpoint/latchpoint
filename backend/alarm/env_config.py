"""
Central environment-variable reading for integration and notification config.

Every ``get_*_config()`` function returns a plain dict whose keys match what
runtime consumers (gateways, dispatchers, connection managers) already expect.
All values fall back to safe defaults so the application can start with zero
env vars configured (everything disabled).

Uses ``django-environ`` (same library as ``config/settings.py``).
"""

from __future__ import annotations

import environ

env = environ.Env()

# ---------------------------------------------------------------------------
# Core integrations
# ---------------------------------------------------------------------------


def get_home_assistant_config() -> dict:
    return {
        "enabled": env.bool("HA_ENABLED", default=False),
        "base_url": env.str("HA_BASE_URL", default="http://localhost:8123"),
        "token": env.str("HA_TOKEN", default=""),
        "connect_timeout_seconds": env.float("HA_CONNECT_TIMEOUT", default=2),
    }


def get_mqtt_config() -> dict:
    return {
        "enabled": env.bool("MQTT_ENABLED", default=False),
        "host": env.str("MQTT_HOST", default="localhost"),
        "port": env.int("MQTT_PORT", default=1883),
        "username": env.str("MQTT_USERNAME", default=""),
        "password": env.str("MQTT_PASSWORD", default=""),
        "use_tls": env.bool("MQTT_USE_TLS", default=False),
        "tls_insecure": env.bool("MQTT_TLS_INSECURE", default=False),
        "client_id": env.str("MQTT_CLIENT_ID", default="latchpoint-alarm"),
        "keepalive_seconds": env.int("MQTT_KEEPALIVE_SECONDS", default=30),
        "connect_timeout_seconds": env.float("MQTT_CONNECT_TIMEOUT", default=5),
    }


def get_zwavejs_config() -> dict:
    return {
        "enabled": env.bool("ZWAVEJS_ENABLED", default=False),
        "ws_url": env.str("ZWAVEJS_WS_URL", default="ws://localhost:3000"),
        "api_token": env.str("ZWAVEJS_API_TOKEN", default=""),
        "connect_timeout_seconds": env.float("ZWAVEJS_CONNECT_TIMEOUT", default=5),
        "reconnect_min_seconds": env.int("ZWAVEJS_RECONNECT_MIN", default=1),
        "reconnect_max_seconds": env.int("ZWAVEJS_RECONNECT_MAX", default=30),
    }


def get_zigbee2mqtt_config() -> dict:
    allowlist_raw = env.str("ZIGBEE2MQTT_ALLOWLIST", default="")
    denylist_raw = env.str("ZIGBEE2MQTT_DENYLIST", default="")
    kinds_raw = env.str("ZIGBEE2MQTT_RUN_RULES_KINDS", default="")
    return {
        "enabled": env.bool("ZIGBEE2MQTT_ENABLED", default=False),
        "base_topic": env.str("ZIGBEE2MQTT_BASE_TOPIC", default="zigbee2mqtt"),
        "allowlist": [s.strip() for s in allowlist_raw.split(",") if s.strip()] if allowlist_raw.strip() else [],
        "denylist": [s.strip() for s in denylist_raw.split(",") if s.strip()] if denylist_raw.strip() else [],
        "run_rules_on_event": env.bool("ZIGBEE2MQTT_RUN_RULES_ON_EVENT", default=False),
        "run_rules_debounce_seconds": env.int("ZIGBEE2MQTT_RUN_RULES_DEBOUNCE_SECONDS", default=5),
        "run_rules_max_per_minute": env.int("ZIGBEE2MQTT_RUN_RULES_MAX_PER_MINUTE", default=60),
        "run_rules_kinds": [s.strip() for s in kinds_raw.split(",") if s.strip()] if kinds_raw.strip() else [],
    }


def get_frigate_config() -> dict:
    return {
        "enabled": env.bool("FRIGATE_ENABLED", default=False),
        "events_topic": env.str("FRIGATE_EVENTS_TOPIC", default="frigate/events"),
        "retention_seconds": env.int("FRIGATE_RETENTION_SECONDS", default=3600),
    }


# ---------------------------------------------------------------------------
# Notification providers
# ---------------------------------------------------------------------------


def get_pushbullet_config() -> dict:
    return {
        "enabled": env.bool("PUSHBULLET_ENABLED", default=False),
        "access_token": env.str("PUSHBULLET_ACCESS_TOKEN", default=""),
        "target_type": env.str("PUSHBULLET_TARGET_TYPE", default="all"),
        "default_device_iden": env.str("PUSHBULLET_DEVICE_IDEN", default=""),
        "default_email": env.str("PUSHBULLET_EMAIL", default=""),
        "default_channel_tag": env.str("PUSHBULLET_CHANNEL_TAG", default=""),
    }


def get_discord_config() -> dict:
    return {
        "enabled": env.bool("DISCORD_ENABLED", default=False),
        "webhook_url": env.str("DISCORD_WEBHOOK_URL", default=""),
        "username": env.str("DISCORD_USERNAME", default=""),
        "avatar_url": env.str("DISCORD_AVATAR_URL", default=""),
    }


def get_slack_config() -> dict:
    return {
        "enabled": env.bool("SLACK_ENABLED", default=False),
        "bot_token": env.str("SLACK_BOT_TOKEN", default=""),
        "default_channel": env.str("SLACK_DEFAULT_CHANNEL", default=""),
        "default_username": env.str("SLACK_DEFAULT_USERNAME", default=""),
        "default_icon_emoji": env.str("SLACK_DEFAULT_ICON_EMOJI", default=""),
    }


def get_webhook_config() -> dict:
    return {
        "enabled": env.bool("WEBHOOK_ENABLED", default=False),
        "url": env.str("WEBHOOK_URL", default=""),
        "method": env.str("WEBHOOK_METHOD", default="POST"),
        "content_type": env.str("WEBHOOK_CONTENT_TYPE", default="application/json"),
        "auth_type": env.str("WEBHOOK_AUTH_TYPE", default="none"),
        "auth_value": env.str("WEBHOOK_AUTH_VALUE", default=""),
        "message_field": env.str("WEBHOOK_MESSAGE_FIELD", default="message"),
        "title_field": env.str("WEBHOOK_TITLE_FIELD", default="title"),
    }


def get_ha_notify_config() -> dict:
    return {
        "enabled": env.bool("HA_NOTIFY_ENABLED", default=False),
        "service": env.str("HA_NOTIFY_SERVICE", default="notify.notify"),
    }
