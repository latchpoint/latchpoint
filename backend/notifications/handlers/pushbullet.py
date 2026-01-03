"""
Pushbullet notification handler.

Supports:
- Note pushes (simple text)
- Link pushes (with clickable URL)
- File pushes (with image attachment)
- Target selection (all devices, specific device, email, channel)
"""

import logging

import httpx

from .base import NotificationHandler, NotificationResult

logger = logging.getLogger(__name__)


class PushbulletHandler(NotificationHandler):
    """Handler for Pushbullet push notifications."""

    provider_type = "pushbullet"
    display_name = "Pushbullet"
    encrypted_fields = ["access_token"]

    config_schema = {
        "type": "object",
        "required": ["access_token"],
        "properties": {
            "access_token": {
                "type": "string",
                "title": "Access Token",
                "description": "Get from pushbullet.com → Settings → Access Tokens",
            },
            "target_type": {
                "type": "string",
                "title": "Default Target",
                "enum": ["all", "device", "email", "channel"],
                "default": "all",
            },
            "default_device_iden": {
                "type": "string",
                "title": "Device Identifier",
                "description": "Required if target_type is 'device'",
            },
            "default_email": {
                "type": "string",
                "title": "Email Address",
                "format": "email",
                "description": "Required if target_type is 'email'",
            },
            "default_channel_tag": {
                "type": "string",
                "title": "Channel Tag",
                "description": "Required if target_type is 'channel'",
            },
        },
    }

    BASE_URL = "https://api.pushbullet.com/v2"
    TIMEOUT = 10.0

    def validate_config(self, config: dict) -> list[str]:
        """Validate Pushbullet configuration."""
        errors = []

        access_token = config.get("access_token", "")
        if not access_token:
            errors.append("Access token is required")
        elif not access_token.startswith("o."):
            errors.append("Access token should start with 'o.'")

        target_type = config.get("target_type", "all")
        if target_type == "device" and not config.get("default_device_iden"):
            errors.append("Device identifier is required when target type is 'device'")
        if target_type == "email" and not config.get("default_email"):
            errors.append("Email address is required when target type is 'email'")
        if target_type == "channel" and not config.get("default_channel_tag"):
            errors.append("Channel tag is required when target type is 'channel'")

        return errors

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None,
    ) -> NotificationResult:
        """Send a push notification via Pushbullet."""
        data = data or {}

        # Build push payload
        payload = self._build_payload(config, message, title, data)

        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.post(
                    f"{self.BASE_URL}/pushes",
                    json=payload,
                    headers=self._get_headers(config["access_token"]),
                )

            if response.status_code == 200:
                return NotificationResult.ok(
                    "Notification sent successfully",
                    response=response.json(),
                )
            elif response.status_code == 401:
                return NotificationResult.error(
                    "Invalid access token",
                    code="AUTH_FAILED",
                )
            elif response.status_code == 403:
                return NotificationResult.error(
                    "Access token lacks required permissions",
                    code="FORBIDDEN",
                )
            elif response.status_code == 429:
                return NotificationResult.error(
                    "Rate limit exceeded. Try again later.",
                    code="RATE_LIMITED",
                )
            else:
                error_data = response.json() if response.content else {}
                error_msg = (
                    error_data.get("error", {}).get("message", "Unknown error")
                    if isinstance(error_data.get("error"), dict)
                    else str(error_data.get("error", "Unknown error"))
                )
                return NotificationResult.error(
                    f"Pushbullet API error: {error_msg}",
                    code="API_ERROR",
                    response=error_data,
                )

        except httpx.TimeoutException:
            logger.warning("Pushbullet request timed out")
            return NotificationResult.error(
                "Request to Pushbullet timed out",
                code="TIMEOUT",
            )
        except httpx.RequestError as e:
            logger.exception("Pushbullet network error")
            return NotificationResult.error(
                f"Network error: {e}",
                code="NETWORK_ERROR",
            )
        except Exception as e:
            logger.exception("Unexpected error sending Pushbullet notification")
            return NotificationResult.error(
                f"Unexpected error: {e}",
                code="UNKNOWN_ERROR",
            )

    def list_devices(self, access_token: str) -> list[dict]:
        """
        Fetch list of devices for the account.

        Returns list of dicts with: iden, nickname, model, type, pushable
        """
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    f"{self.BASE_URL}/devices",
                    headers=self._get_headers(access_token),
                )

            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        "iden": d["iden"],
                        "nickname": d.get("nickname", "Unknown Device"),
                        "model": d.get("model"),
                        "type": d.get("type"),
                        "pushable": d.get("pushable", False),
                    }
                    for d in data.get("devices", [])
                    if d.get("active", True) and d.get("pushable", False)
                ]
            return []
        except Exception:
            logger.exception("Failed to list Pushbullet devices")
            return []

    def get_user_info(self, access_token: str) -> dict | None:
        """Fetch user info to validate token."""
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                response = client.get(
                    f"{self.BASE_URL}/users/me",
                    headers=self._get_headers(access_token),
                )

            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            logger.exception("Failed to get Pushbullet user info")
            return None

    def _get_headers(self, access_token: str) -> dict:
        """Build request headers."""
        return {
            "Access-Token": access_token,
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        config: dict,
        message: str,
        title: str | None,
        data: dict,
    ) -> dict:
        """Build the push payload."""
        # Determine push type based on data
        if data.get("image_url"):
            payload = {
                "type": "file",
                "file_url": data["image_url"],
                "file_type": "image/jpeg",
                "body": message,
            }
            if title:
                payload["file_name"] = title
        elif data.get("url"):
            payload = {
                "type": "link",
                "title": title or "Alarm Notification",
                "body": message,
                "url": data["url"],
            }
        else:
            payload = {
                "type": "note",
                "title": title or "Alarm Notification",
                "body": message,
            }

        # Add target
        target = self._resolve_target(config, data)
        payload.update(target)

        return payload

    def _resolve_target(self, config: dict, data: dict) -> dict:
        """Resolve the notification target."""
        # Check for override in notification data
        if override := data.get("target_override"):
            return self._target_to_payload(override)

        # Use default from config
        target_type = config.get("target_type", "all")

        if target_type == "device":
            return {"device_iden": config["default_device_iden"]}
        elif target_type == "email":
            return {"email": config["default_email"]}
        elif target_type == "channel":
            return {"channel_tag": config["default_channel_tag"]}
        else:
            # "all" - no target specified, pushes to all devices
            return {}

    def _target_to_payload(self, target: dict) -> dict:
        """Convert target override to API payload."""
        target_type = target.get("type", "all")

        if target_type == "device":
            return {"device_iden": target["device_iden"]}
        elif target_type == "email":
            return {"email": target["email"]}
        elif target_type == "channel":
            return {"channel_tag": target["channel_tag"]}
        return {}
