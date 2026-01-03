"""
Generic webhook notification handler.

Supports custom HTTP endpoints with configurable method, headers, and auth.
"""

import base64
import logging

import httpx

from .base import NotificationHandler, NotificationResult

logger = logging.getLogger(__name__)


class WebhookHandler(NotificationHandler):
    """Handler for generic webhook notifications."""

    provider_type = "webhook"
    display_name = "Webhook"
    encrypted_fields = ["auth_value"]

    config_schema = {
        "type": "object",
        "required": ["url", "method"],
        "properties": {
            "url": {
                "type": "string",
                "title": "Webhook URL",
                "format": "uri",
                "description": "The endpoint URL to send notifications to",
            },
            "method": {
                "type": "string",
                "title": "HTTP Method",
                "enum": ["POST", "PUT"],
                "default": "POST",
            },
            "content_type": {
                "type": "string",
                "title": "Content Type",
                "enum": ["application/json", "application/x-www-form-urlencoded"],
                "default": "application/json",
            },
            "auth_type": {
                "type": "string",
                "title": "Authentication Type",
                "enum": ["none", "basic", "bearer", "header"],
                "default": "none",
            },
            "auth_value": {
                "type": "string",
                "title": "Auth Credentials",
                "description": "Basic: 'user:pass', Bearer: 'token', Header: 'HeaderName: value'",
            },
            "custom_headers": {
                "type": "object",
                "title": "Custom Headers",
                "description": "Additional HTTP headers as key-value pairs",
                "additionalProperties": {"type": "string"},
            },
            "message_field": {
                "type": "string",
                "title": "Message Field Name",
                "default": "message",
                "description": "JSON field name for the message",
            },
            "title_field": {
                "type": "string",
                "title": "Title Field Name",
                "default": "title",
                "description": "JSON field name for the title",
            },
        },
    }

    TIMEOUT = 10.0

    def validate_config(self, config: dict) -> list[str]:
        """Validate webhook configuration."""
        errors = []

        url = config.get("url", "")
        if not url:
            errors.append("Webhook URL is required")
        elif not url.startswith(("http://", "https://")):
            errors.append("URL must start with http:// or https://")

        method = config.get("method", "POST")
        if method not in ("POST", "PUT"):
            errors.append("Method must be POST or PUT")

        auth_type = config.get("auth_type", "none")
        if auth_type != "none" and not config.get("auth_value"):
            errors.append(f"Auth value is required for auth type '{auth_type}'")

        if auth_type == "basic":
            auth_value = config.get("auth_value", "")
            if auth_value and ":" not in auth_value:
                errors.append("Basic auth value must be in 'username:password' format")

        if auth_type == "header":
            auth_value = config.get("auth_value", "")
            if auth_value and ":" not in auth_value:
                errors.append("Header auth value must be in 'Header-Name: value' format")

        return errors

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None,
    ) -> NotificationResult:
        """Send a notification via webhook."""
        data = data or {}

        url = config["url"]
        method = config.get("method", "POST")
        content_type = config.get("content_type", "application/json")

        # Build headers
        headers = self._build_headers(config, content_type)

        # Build payload
        payload = self._build_payload(config, message, title, data)

        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                if content_type == "application/json":
                    response = client.request(
                        method,
                        url,
                        json=payload,
                        headers=headers,
                    )
                else:
                    response = client.request(
                        method,
                        url,
                        data=payload,
                        headers=headers,
                    )

            # Accept any 2xx status as success
            if 200 <= response.status_code < 300:
                response_data = None
                if response.content:
                    try:
                        response_data = response.json()
                    except Exception:
                        response_data = {"raw": response.text[:500]}
                return NotificationResult.ok(
                    f"Webhook returned {response.status_code}",
                    response=response_data,
                )
            elif response.status_code == 401:
                return NotificationResult.error(
                    "Authentication failed",
                    code="UNAUTHORIZED",
                )
            elif response.status_code == 403:
                return NotificationResult.error(
                    "Access forbidden",
                    code="FORBIDDEN",
                )
            elif response.status_code == 404:
                return NotificationResult.error(
                    "Webhook endpoint not found",
                    code="NOT_FOUND",
                )
            elif response.status_code == 429:
                return NotificationResult.error(
                    "Rate limited. Try again later.",
                    code="RATE_LIMITED",
                )
            else:
                return NotificationResult.error(
                    f"Webhook returned {response.status_code}",
                    code="API_ERROR",
                )

        except httpx.TimeoutException:
            logger.warning("Webhook request timed out")
            return NotificationResult.error(
                "Request timed out",
                code="TIMEOUT",
            )
        except httpx.RequestError as e:
            logger.exception("Webhook network error")
            return NotificationResult.error(
                f"Network error: {e}",
                code="NETWORK_ERROR",
            )
        except Exception as e:
            logger.exception("Unexpected error sending webhook notification")
            return NotificationResult.error(
                f"Unexpected error: {e}",
                code="UNKNOWN_ERROR",
            )

    def _build_headers(self, config: dict, content_type: str) -> dict:
        """Build HTTP headers with auth and custom headers."""
        headers = {"Content-Type": content_type}

        # Add custom headers
        if custom_headers := config.get("custom_headers"):
            headers.update(custom_headers)

        # Add auth header
        auth_type = config.get("auth_type", "none")
        auth_value = config.get("auth_value", "")

        if auth_type == "basic" and auth_value:
            encoded = base64.b64encode(auth_value.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        elif auth_type == "bearer" and auth_value:
            headers["Authorization"] = f"Bearer {auth_value}"
        elif auth_type == "header" and auth_value:
            if ":" in auth_value:
                header_name, header_value = auth_value.split(":", 1)
                headers[header_name.strip()] = header_value.strip()

        return headers

    def _build_payload(
        self,
        config: dict,
        message: str,
        title: str | None,
        data: dict,
    ) -> dict:
        """Build webhook payload."""
        message_field = config.get("message_field", "message")
        title_field = config.get("title_field", "title")

        payload = {message_field: message}

        if title:
            payload[title_field] = title

        # Merge any custom data
        if custom_data := data.get("custom_data"):
            payload.update(custom_data)

        return payload
