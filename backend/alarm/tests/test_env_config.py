"""Tests for alarm.env_config — env-variable-based config readers."""

from __future__ import annotations

from django.test import SimpleTestCase


class HomeAssistantConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_home_assistant_config

        cfg = get_home_assistant_config()
        self.assertEqual(cfg["base_url"], "http://localhost:8123")
        self.assertEqual(cfg["token"], "")
        self.assertEqual(cfg["connect_timeout_seconds"], 2)
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self, monkeypatch=None):
        import os
        from unittest.mock import patch

        env = {
            "HA_BASE_URL": "http://ha.local:8123",
            "HA_TOKEN": "my-secret-token",
            "HA_CONNECT_TIMEOUT": "10",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_home_assistant_config

            cfg = get_home_assistant_config()
            self.assertEqual(cfg["base_url"], "http://ha.local:8123")
            self.assertEqual(cfg["token"], "my-secret-token")
            self.assertEqual(cfg["connect_timeout_seconds"], 10)
            self.assertNotIn("enabled", cfg)


class MqttConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_mqtt_config

        cfg = get_mqtt_config()
        self.assertEqual(cfg["host"], "localhost")
        self.assertEqual(cfg["port"], 1883)
        self.assertEqual(cfg["username"], "")
        self.assertEqual(cfg["password"], "")
        self.assertFalse(cfg["use_tls"])
        self.assertFalse(cfg["tls_insecure"])
        self.assertEqual(cfg["client_id"], "latchpoint-alarm")
        self.assertEqual(cfg["keepalive_seconds"], 30)
        self.assertEqual(cfg["connect_timeout_seconds"], 5)
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self):
        import os
        from unittest.mock import patch

        env = {
            "MQTT_HOST": "broker.local",
            "MQTT_PORT": "8883",
            "MQTT_USERNAME": "user",
            "MQTT_PASSWORD": "pass",
            "MQTT_USE_TLS": "true",
            "MQTT_TLS_INSECURE": "true",
            "MQTT_CLIENT_ID": "my-client",
            "MQTT_KEEPALIVE_SECONDS": "60",
            "MQTT_CONNECT_TIMEOUT": "10",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_mqtt_config

            cfg = get_mqtt_config()
            self.assertEqual(cfg["host"], "broker.local")
            self.assertEqual(cfg["port"], 8883)
            self.assertEqual(cfg["username"], "user")
            self.assertEqual(cfg["password"], "pass")
            self.assertTrue(cfg["use_tls"])
            self.assertTrue(cfg["tls_insecure"])
            self.assertEqual(cfg["client_id"], "my-client")
            self.assertEqual(cfg["keepalive_seconds"], 60)
            self.assertEqual(cfg["connect_timeout_seconds"], 10)
            self.assertNotIn("enabled", cfg)


class ZwavejsConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_zwavejs_config

        cfg = get_zwavejs_config()
        self.assertEqual(cfg["ws_url"], "ws://localhost:3000")
        self.assertEqual(cfg["api_token"], "")
        self.assertEqual(cfg["connect_timeout_seconds"], 5)
        self.assertEqual(cfg["reconnect_min_seconds"], 1)
        self.assertEqual(cfg["reconnect_max_seconds"], 30)
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self):
        import os
        from unittest.mock import patch

        env = {
            "ZWAVEJS_WS_URL": "ws://zwave.local:3000",
            "ZWAVEJS_API_TOKEN": "secret-token",
            "ZWAVEJS_CONNECT_TIMEOUT": "15",
            "ZWAVEJS_RECONNECT_MIN": "2",
            "ZWAVEJS_RECONNECT_MAX": "60",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_zwavejs_config

            cfg = get_zwavejs_config()
            self.assertEqual(cfg["ws_url"], "ws://zwave.local:3000")
            self.assertEqual(cfg["api_token"], "secret-token")
            self.assertEqual(cfg["connect_timeout_seconds"], 15)
            self.assertEqual(cfg["reconnect_min_seconds"], 2)
            self.assertEqual(cfg["reconnect_max_seconds"], 60)
            self.assertNotIn("enabled", cfg)


class PushbulletConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_pushbullet_config

        cfg = get_pushbullet_config()
        self.assertEqual(cfg["access_token"], "")
        self.assertEqual(cfg["target_type"], "all")
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self):
        import os
        from unittest.mock import patch

        env = {
            "PUSHBULLET_ACCESS_TOKEN": "o.abc123",
            "PUSHBULLET_TARGET_TYPE": "device",
            "PUSHBULLET_DEVICE_IDEN": "dev123",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_pushbullet_config

            cfg = get_pushbullet_config()
            self.assertEqual(cfg["access_token"], "o.abc123")
            self.assertEqual(cfg["target_type"], "device")
            self.assertEqual(cfg["default_device_iden"], "dev123")
            self.assertNotIn("enabled", cfg)


class DiscordConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_discord_config

        cfg = get_discord_config()
        self.assertEqual(cfg["webhook_url"], "")
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self):
        import os
        from unittest.mock import patch

        env = {
            "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
            "DISCORD_USERNAME": "AlarmBot",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_discord_config

            cfg = get_discord_config()
            self.assertEqual(cfg["webhook_url"], "https://discord.com/api/webhooks/123/abc")
            self.assertEqual(cfg["username"], "AlarmBot")
            self.assertNotIn("enabled", cfg)


class SlackConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_slack_config

        cfg = get_slack_config()
        self.assertEqual(cfg["bot_token"], "")
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self):
        import os
        from unittest.mock import patch

        env = {
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "SLACK_DEFAULT_CHANNEL": "C012345",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_slack_config

            cfg = get_slack_config()
            self.assertEqual(cfg["bot_token"], "xoxb-test-token")
            self.assertEqual(cfg["default_channel"], "C012345")
            self.assertNotIn("enabled", cfg)


class WebhookConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_webhook_config

        cfg = get_webhook_config()
        self.assertEqual(cfg["url"], "")
        self.assertEqual(cfg["method"], "POST")
        self.assertEqual(cfg["content_type"], "application/json")
        self.assertEqual(cfg["auth_type"], "none")
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self):
        import os
        from unittest.mock import patch

        env = {
            "WEBHOOK_URL": "https://hook.example.com/alarm",
            "WEBHOOK_METHOD": "PUT",
            "WEBHOOK_AUTH_TYPE": "bearer",
            "WEBHOOK_AUTH_VALUE": "my-token",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_webhook_config

            cfg = get_webhook_config()
            self.assertEqual(cfg["url"], "https://hook.example.com/alarm")
            self.assertEqual(cfg["method"], "PUT")
            self.assertEqual(cfg["auth_type"], "bearer")
            self.assertEqual(cfg["auth_value"], "my-token")
            self.assertNotIn("enabled", cfg)


class HaNotifyConfigTest(SimpleTestCase):
    def test_defaults(self):
        from alarm.env_config import get_ha_notify_config

        cfg = get_ha_notify_config()
        self.assertEqual(cfg["service"], "notify.notify")
        self.assertNotIn("enabled", cfg)

    def test_env_overrides(self):
        import os
        from unittest.mock import patch

        env = {
            "HA_NOTIFY_SERVICE": "notify.mobile_app_phone",
        }
        with patch.dict(os.environ, env):
            from alarm.env_config import get_ha_notify_config

            cfg = get_ha_notify_config()
            self.assertEqual(cfg["service"], "notify.mobile_app_phone")
            self.assertNotIn("enabled", cfg)
