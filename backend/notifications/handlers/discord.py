"""
Discord notification handler.

Uses Discord webhooks for sending notifications.
"""

import logging

import httpx

from .base import NotificationHandler, NotificationResult

logger = logging.getLogger(__name__)


class DiscordHandler(NotificationHandler):
    """Handler for Discord webhook notifications."""

    provider_type = "discord"
    display_name = "Discord"
    encrypted_fields = ["webhook_url"]

    config_schema = {
        "type": "object",
        "required": ["webhook_url"],
        "properties": {
            "webhook_url": {
                "type": "string",
                "title": "Webhook URL",
                "description": "Right-click channel → Edit Channel → Integrations → Webhooks",
                "pattern": "^https://discord\\.com/api/webhooks/.*$",
            },
            "username": {
                "type": "string",
                "title": "Bot Username",
                "description": "Override the webhook's default username",
            },
            "avatar_url": {
                "type": "string",
                "title": "Avatar URL",
                "description": "Override the webhook's default avatar",
            },
        },
    }

    TIMEOUT = 10.0

    def validate_config(self, config: dict) -> list[str]:
        """Validate Discord configuration."""
        errors = []

        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            errors.append("Webhook URL is required")
        elif not webhook_url.startswith("https://discord.com/api/webhooks/"):
            errors.append("Webhook URL must be a Discord webhook URL")

        return errors

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None,
    ) -> NotificationResult:
        """Send a message via Discord webhook."""
        data = data or {}
        webhook_url = config["webhook_url"]

        # Build payload
        payload = self._build_payload(config, message, title, data)

        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.post(
                    webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

            # Discord returns 204 No Content on success
            if response.status_code in (200, 204):
                return NotificationResult.ok("Message sent to Discord")
            elif response.status_code == 400:
                error_data = response.json() if response.content else {}
                return NotificationResult.error(
                    f"Bad request: {error_data.get('message', 'Invalid payload')}",
                    code="BAD_REQUEST",
                    response=error_data,
                )
            elif response.status_code == 401:
                return NotificationResult.error(
                    "Invalid webhook URL",
                    code="UNAUTHORIZED",
                )
            elif response.status_code == 404:
                return NotificationResult.error(
                    "Webhook not found - it may have been deleted",
                    code="NOT_FOUND",
                )
            elif response.status_code == 429:
                return NotificationResult.error(
                    "Rate limited by Discord. Try again later.",
                    code="RATE_LIMITED",
                )
            else:
                error_data = response.json() if response.content else {}
                return NotificationResult.error(
                    f"Discord error ({response.status_code}): {error_data.get('message', 'Unknown')}",
                    code="API_ERROR",
                    response=error_data,
                )

        except httpx.TimeoutException:
            logger.warning("Discord webhook request timed out")
            return NotificationResult.error(
                "Request to Discord timed out",
                code="TIMEOUT",
            )
        except httpx.RequestError as e:
            logger.exception("Discord network error")
            return NotificationResult.error(
                f"Network error: {e}",
                code="NETWORK_ERROR",
            )
        except Exception as e:
            logger.exception("Unexpected error sending Discord notification")
            return NotificationResult.error(
                f"Unexpected error: {e}",
                code="UNKNOWN_ERROR",
            )

    def _build_payload(
        self,
        config: dict,
        message: str,
        title: str | None,
        data: dict,
    ) -> dict:
        """Build Discord webhook payload."""
        payload: dict = {}

        # Override username/avatar if configured
        if username := config.get("username"):
            payload["username"] = username
        if avatar_url := config.get("avatar_url"):
            payload["avatar_url"] = avatar_url

        # Check if we should use embed
        if title or data.get("color") or data.get("image_url"):
            embed = {"description": message}

            if title:
                embed["title"] = title

            if color := data.get("color"):
                # Accept hex color or integer
                if isinstance(color, str) and color.startswith("#"):
                    embed["color"] = int(color[1:], 16)
                else:
                    embed["color"] = int(color)

            if image_url := data.get("image_url"):
                embed["image"] = {"url": image_url}

            if thumbnail_url := data.get("thumbnail_url"):
                embed["thumbnail"] = {"url": thumbnail_url}

            if footer := data.get("footer"):
                embed["footer"] = {"text": footer}

            payload["embeds"] = [embed]
        else:
            # Simple content message
            payload["content"] = message

        return payload
