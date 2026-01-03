"""
Home Assistant notification handler.

This handler wraps the existing Home Assistant integration to provide a unified
notification interface. It delegates to the HA gateway for actual API calls.
"""

import logging

from .base import NotificationHandler, NotificationResult

logger = logging.getLogger(__name__)


class HomeAssistantHandler(NotificationHandler):
    """
    Handler for Home Assistant notify services.

    This handler uses the existing HA connection configured in the integrations
    module. It provides a consistent interface with other notification providers
    while reusing the HA infrastructure.
    """

    provider_type = "home_assistant"
    display_name = "Home Assistant"
    encrypted_fields = []  # HA credentials are managed by integrations_home_assistant

    config_schema = {
        "type": "object",
        "required": ["service"],
        "properties": {
            "service": {
                "type": "string",
                "title": "Notify Service",
                "description": "HA notify service (e.g., notify.mobile_app_iphone)",
                "pattern": "^notify\\..+$",
            },
        },
    }

    def validate_config(self, config: dict) -> list[str]:
        """Validate Home Assistant notification configuration."""
        errors = []
        service = config.get("service", "")

        if not service:
            errors.append("Service is required")
        elif not service.startswith("notify."):
            errors.append("Service must start with 'notify.'")
        elif len(service) <= 7:  # "notify." is 7 chars
            errors.append("Service name is too short")

        return errors

    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None,
    ) -> NotificationResult:
        """Send notification via Home Assistant notify service."""
        try:
            # Import here to avoid circular imports and allow testing without HA
            from integrations_home_assistant import api as ha_api

            service = config["service"]

            # Parse service name (notify.xxx -> domain=notify, service=xxx)
            if "." not in service:
                return NotificationResult.error(
                    f"Invalid service format: {service}",
                    code="INVALID_SERVICE",
                )

            domain, service_name = service.split(".", 1)

            # Build service data
            service_data = {"message": message}
            if title:
                service_data["title"] = title
            if data:
                # Merge additional data (e.g., for iOS critical alerts)
                service_data["data"] = data

            # Call Home Assistant service
            ha_api.call_service(
                domain=domain,
                service=service_name,
                service_data=service_data,
            )

            return NotificationResult.ok(f"Sent via {service}")

        except RuntimeError as e:
            # HA connection error
            error_msg = str(e)
            if "not configured" in error_msg.lower():
                return NotificationResult.error(
                    "Home Assistant not configured",
                    code="HA_NOT_CONFIGURED",
                )
            elif "not reachable" in error_msg.lower():
                return NotificationResult.error(
                    "Home Assistant not reachable",
                    code="HA_NOT_REACHABLE",
                )
            else:
                return NotificationResult.error(
                    f"Home Assistant error: {error_msg}",
                    code="HA_ERROR",
                )
        except Exception as e:
            logger.exception("Unexpected error sending HA notification")
            return NotificationResult.error(
                f"Unexpected error: {e}",
                code="UNKNOWN_ERROR",
            )

    @staticmethod
    def list_available_services() -> list[str]:
        """
        List available notify services from Home Assistant.

        Returns list of service names like ["notify.notify", "notify.mobile_app_iphone"]
        """
        try:
            from integrations_home_assistant import api as ha_api

            return ha_api.list_notify_services()
        except Exception:
            logger.exception("Failed to list HA notify services")
            return []
