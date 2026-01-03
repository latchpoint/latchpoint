"""
Slack notification handler.

Uses Slack Web API (chat.postMessage) with a Bot User OAuth Token (xoxb-...).
"""

from __future__ import annotations

import logging

import httpx

from .base import NotificationHandler, NotificationResult

logger = logging.getLogger(__name__)


class SlackHandler(NotificationHandler):
    provider_type = "slack"
    display_name = "Slack"
    encrypted_fields = ["bot_token"]

    config_schema = {
        "type": "object",
        "required": ["bot_token", "default_channel"],
        "properties": {
            "bot_token": {
                "type": "string",
                "title": "Bot Token",
                "description": "Slack Bot token (starts with xoxb-)",
            },
            "default_channel": {
                "type": "string",
                "title": "Default Channel",
                "description": "Slack channel ID (e.g., C0123456789)",
            },
            "default_username": {
                "type": "string",
                "title": "Default Username (optional)",
            },
            "default_icon_emoji": {
                "type": "string",
                "title": "Default Icon Emoji (optional)",
                "description": "e.g. :rotating_light:",
            },
        },
    }

    BASE_URL = "https://slack.com/api"
    TIMEOUT = 10.0

    def validate_config(self, config: dict) -> list[str]:
        errors: list[str] = []

        bot_token = config.get("bot_token", "")
        if not bot_token:
            errors.append("Bot token is required")
        elif not isinstance(bot_token, str) or not bot_token.startswith("xoxb-"):
            errors.append("Bot token must start with 'xoxb-'")

        default_channel = config.get("default_channel", "")
        if not default_channel:
            errors.append("Default channel is required")

        return errors

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None,
    ) -> NotificationResult:
        data = data or {}

        bot_token = config.get("bot_token")
        default_channel = config.get("default_channel")
        if not isinstance(bot_token, str) or not bot_token:
            return NotificationResult.error("Missing bot token", code="INVALID_CONFIG")
        if not isinstance(default_channel, str) or not default_channel:
            return NotificationResult.error("Missing default channel", code="INVALID_CONFIG")

        channel = data.get("channel") or default_channel
        if not isinstance(channel, str) or not channel:
            return NotificationResult.error("No channel specified", code="INVALID_CONFIG")

        payload = self._build_payload(config=config, channel=channel, message=message, title=title, data=data)

        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.post(
                    f"{self.BASE_URL}/chat.postMessage",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {bot_token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                )

            if response.status_code == 429:
                return NotificationResult.error(
                    "Slack rate limit exceeded. Try again later.",
                    code="RATE_LIMITED",
                )
            if response.status_code >= 500:
                return NotificationResult.error(
                    "Slack service unavailable",
                    code="SERVER_ERROR",
                )
            if response.status_code != 200:
                return NotificationResult.error(
                    f"Slack API returned HTTP {response.status_code}",
                    code="API_ERROR",
                )

            body = response.json() if response.content else {}
            if isinstance(body, dict) and body.get("ok") is True:
                return NotificationResult.ok("Notification sent successfully", response=body)

            slack_error = ""
            if isinstance(body, dict):
                slack_error = str(body.get("error") or "")
            msg = f"Slack API error{': ' + slack_error if slack_error else ''}"
            return NotificationResult.error(msg, code="API_ERROR", response=body if isinstance(body, dict) else None)

        except httpx.TimeoutException:
            return NotificationResult.error("Request to Slack timed out", code="TIMEOUT")
        except httpx.RequestError as exc:
            logger.exception("Slack network error")
            return NotificationResult.error(f"Network error: {exc}", code="NETWORK_ERROR")
        except Exception as exc:
            logger.exception("Unexpected error sending Slack notification")
            return NotificationResult.error(f"Unexpected error: {exc}", code="UNKNOWN_ERROR")

    def _build_payload(
        self,
        *,
        config: dict,
        channel: str,
        message: str,
        title: str | None,
        data: dict,
    ) -> dict:
        text = message
        if title:
            text = f"*{title}*\n{message}"

        payload: dict = {"channel": channel, "text": text}

        username = data.get("username") or config.get("default_username")
        if isinstance(username, str) and username:
            payload["username"] = username

        icon_emoji = data.get("icon_emoji") or config.get("default_icon_emoji")
        if isinstance(icon_emoji, str) and icon_emoji:
            payload["icon_emoji"] = icon_emoji

        blocks = data.get("blocks")
        if isinstance(blocks, list):
            payload["blocks"] = blocks

        attachments = data.get("attachments")
        if isinstance(attachments, list):
            payload["attachments"] = attachments

        return payload

    def test(self, config: dict) -> NotificationResult:
        return self.send(
            config=config,
            message="Test notification from alarm system",
            title="Test",
        )

