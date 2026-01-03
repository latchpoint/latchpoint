"""
Tests for notification handlers.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from notifications.handlers.base import NotificationResult
from notifications.handlers.discord import DiscordHandler
from notifications.handlers.home_assistant import HomeAssistantHandler
from notifications.handlers.pushbullet import PushbulletHandler
from notifications.handlers.slack import SlackHandler
from notifications.handlers.webhook import WebhookHandler


class TestPushbulletHandler(TestCase):
    """Tests for PushbulletHandler."""

    def setUp(self):
        self.handler = PushbulletHandler()

    def test_validate_config_valid(self):
        """Valid config should pass validation."""
        config = {"access_token": "o.valid_token"}
        errors = self.handler.validate_config(config)
        self.assertEqual(errors, [])

    def test_validate_config_missing_token(self):
        """Missing token should fail validation."""
        config = {}
        errors = self.handler.validate_config(config)
        self.assertIn("Access token is required", errors)

    def test_validate_config_invalid_token_format(self):
        """Token not starting with 'o.' should fail."""
        config = {"access_token": "invalid_token"}
        errors = self.handler.validate_config(config)
        self.assertIn("Access token should start with 'o.'", errors)

    def test_validate_config_device_target_missing_iden(self):
        """Device target without iden should fail."""
        config = {
            "access_token": "o.valid",
            "target_type": "device",
        }
        errors = self.handler.validate_config(config)
        self.assertIn(
            "Device identifier is required when target type is 'device'", errors
        )

    def test_build_payload_note(self):
        """Test building a note payload."""
        config = {"access_token": "o.test"}
        payload = self.handler._build_payload(config, "Test message", "Test Title", {})
        self.assertEqual(payload["type"], "note")
        self.assertEqual(payload["body"], "Test message")
        self.assertEqual(payload["title"], "Test Title")

    def test_build_payload_link(self):
        """Test building a link payload."""
        config = {"access_token": "o.test"}
        payload = self.handler._build_payload(
            config, "Check this", "Link", {"url": "https://example.com"}
        )
        self.assertEqual(payload["type"], "link")
        self.assertEqual(payload["url"], "https://example.com")

    def test_build_payload_with_device_target(self):
        """Test payload includes device target."""
        config = {
            "access_token": "o.test",
            "target_type": "device",
            "default_device_iden": "device123",
        }
        payload = self.handler._build_payload(config, "Test", None, {})
        self.assertEqual(payload["device_iden"], "device123")


class TestDiscordHandler(TestCase):
    """Tests for DiscordHandler."""

    def setUp(self):
        self.handler = DiscordHandler()

    def test_validate_config_valid(self):
        """Valid config should pass validation."""
        config = {"webhook_url": "https://discord.com/api/webhooks/123/abc"}
        errors = self.handler.validate_config(config)
        self.assertEqual(errors, [])

    def test_validate_config_missing_url(self):
        """Missing webhook URL should fail."""
        config = {}
        errors = self.handler.validate_config(config)
        self.assertIn("Webhook URL is required", errors)

    def test_validate_config_invalid_url(self):
        """Non-Discord URL should fail."""
        config = {"webhook_url": "https://example.com/webhook"}
        errors = self.handler.validate_config(config)
        self.assertIn("Webhook URL must be a Discord webhook URL", errors)

    def test_build_payload_simple(self):
        """Test simple content payload."""
        config = {"webhook_url": "https://discord.com/api/webhooks/123/abc"}
        payload = self.handler._build_payload(config, "Test message", None, {})
        self.assertEqual(payload["content"], "Test message")
        self.assertNotIn("embeds", payload)

    def test_build_payload_embed(self):
        """Test embed payload with title."""
        config = {"webhook_url": "https://discord.com/api/webhooks/123/abc"}
        payload = self.handler._build_payload(config, "Test message", "Title", {})
        self.assertIn("embeds", payload)
        self.assertEqual(payload["embeds"][0]["title"], "Title")
        self.assertEqual(payload["embeds"][0]["description"], "Test message")


class TestWebhookHandler(TestCase):
    """Tests for WebhookHandler."""

    def setUp(self):
        self.handler = WebhookHandler()

    def test_validate_config_valid(self):
        """Valid config should pass validation."""
        config = {"url": "https://example.com/webhook", "method": "POST"}
        errors = self.handler.validate_config(config)
        self.assertEqual(errors, [])

    def test_validate_config_missing_url(self):
        """Missing URL should fail."""
        config = {"method": "POST"}
        errors = self.handler.validate_config(config)
        self.assertIn("Webhook URL is required", errors)

    def test_validate_config_invalid_method(self):
        """Invalid method should fail."""
        config = {"url": "https://example.com", "method": "GET"}
        errors = self.handler.validate_config(config)
        self.assertIn("Method must be POST or PUT", errors)

    def test_validate_config_basic_auth_format(self):
        """Basic auth needs user:pass format."""
        config = {
            "url": "https://example.com",
            "method": "POST",
            "auth_type": "basic",
            "auth_value": "no_colon",
        }
        errors = self.handler.validate_config(config)
        self.assertIn(
            "Basic auth value must be in 'username:password' format", errors
        )

    def test_build_headers_basic_auth(self):
        """Test basic auth header generation."""
        config = {
            "auth_type": "basic",
            "auth_value": "user:pass",
        }
        headers = self.handler._build_headers(config, "application/json")
        self.assertIn("Authorization", headers)
        self.assertTrue(headers["Authorization"].startswith("Basic "))

    def test_build_headers_bearer_auth(self):
        """Test bearer auth header generation."""
        config = {
            "auth_type": "bearer",
            "auth_value": "my_token",
        }
        headers = self.handler._build_headers(config, "application/json")
        self.assertEqual(headers["Authorization"], "Bearer my_token")


class TestHomeAssistantHandler(TestCase):
    """Tests for HomeAssistantHandler."""

    def setUp(self):
        self.handler = HomeAssistantHandler()

    def test_validate_config_valid(self):
        """Valid config should pass validation."""
        config = {"service": "notify.mobile_app_phone"}
        errors = self.handler.validate_config(config)
        self.assertEqual(errors, [])

    def test_validate_config_missing_service(self):
        """Missing service should fail."""
        config = {}
        errors = self.handler.validate_config(config)
        self.assertIn("Service is required", errors)

    def test_validate_config_invalid_service_prefix(self):
        """Service not starting with notify. should fail."""
        config = {"service": "light.turn_on"}
        errors = self.handler.validate_config(config)
        self.assertIn("Service must start with 'notify.'", errors)

    def test_validate_config_service_too_short(self):
        """Service with nothing after notify. should fail."""
        config = {"service": "notify."}
        errors = self.handler.validate_config(config)
        self.assertIn("Service name is too short", errors)


class TestSlackHandler(TestCase):
    """Tests for SlackHandler."""

    def setUp(self):
        self.handler = SlackHandler()

    def test_validate_config_valid(self):
        config = {"bot_token": "xoxb-valid", "default_channel": "C123"}
        errors = self.handler.validate_config(config)
        self.assertEqual(errors, [])

    def test_validate_config_missing_token(self):
        config = {"default_channel": "C123"}
        errors = self.handler.validate_config(config)
        self.assertIn("Bot token is required", errors)

    def test_validate_config_invalid_token_prefix(self):
        config = {"bot_token": "xoxp-user-token", "default_channel": "C123"}
        errors = self.handler.validate_config(config)
        self.assertIn("Bot token must start with 'xoxb-'", errors)

    def test_build_payload_includes_title(self):
        payload = self.handler._build_payload(
            config={"default_username": "Alarm"},
            channel="C123",
            message="Hello",
            title="Title",
            data={},
        )
        self.assertEqual(payload["channel"], "C123")
        self.assertEqual(payload["text"], "*Title*\nHello")

    @patch("httpx.Client.post")
    def test_send_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"ok": true}'
        mock_response.json.return_value = {"ok": True}
        mock_post.return_value = mock_response

        result = self.handler.send(
            config={"bot_token": "xoxb-valid", "default_channel": "C123"},
            message="Hello",
            title=None,
            data=None,
        )
        self.assertTrue(result.success)

    @patch("httpx.Client.post")
    def test_send_rate_limited(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.content = b"{}"
        mock_response.json.return_value = {}
        mock_post.return_value = mock_response

        result = self.handler.send(
            config={"bot_token": "xoxb-valid", "default_channel": "C123"},
            message="Hello",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "RATE_LIMITED")


class TestNotificationResult(TestCase):
    """Tests for NotificationResult dataclass."""

    def test_ok_result(self):
        """Test creating success result."""
        result = NotificationResult.ok("Sent", response={"id": 123})
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Sent")
        self.assertIsNone(result.error_code)
        self.assertEqual(result.provider_response, {"id": 123})

    def test_error_result(self):
        """Test creating error result."""
        result = NotificationResult.error("Failed", code="AUTH_ERROR")
        self.assertFalse(result.success)
        self.assertEqual(result.message, "Failed")
        self.assertEqual(result.error_code, "AUTH_ERROR")
