"""
Base notification handler protocol and result types.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""

    success: bool
    message: str
    error_code: str | None = None
    provider_response: dict | None = None

    @classmethod
    def ok(
        cls, message: str = "Sent successfully", response: dict | None = None
    ) -> "NotificationResult":
        """Create a successful result."""
        return cls(success=True, message=message, provider_response=response)

    @classmethod
    def error(
        cls,
        message: str,
        code: str = "ERROR",
        response: dict | None = None,
    ) -> "NotificationResult":
        """Create an error result."""
        return cls(
            success=False,
            message=message,
            error_code=code,
            provider_response=response,
        )


@dataclass
class ProviderConfigField:
    """Describes a field in the provider configuration schema."""

    name: str
    field_type: str  # "text", "password", "email", "number", "select", "checkbox"
    required: bool = True
    label: str = ""
    description: str = ""
    placeholder: str = ""
    options: list[dict] = field(default_factory=list)  # For select type


class NotificationHandler(ABC):
    """
    Abstract base class for notification handlers.

    Each handler must implement:
        - provider_type: Unique identifier for this provider
        - display_name: Human-readable name
        - encrypted_fields: List of config fields that should be encrypted
        - config_schema: JSON Schema for configuration validation
        - validate_config(): Validate configuration
        - send(): Send a notification
        - test(): Send a test notification
    """

    # Override in subclasses
    provider_type: str = ""
    display_name: str = ""
    encrypted_fields: list[str] = []
    config_schema: dict = {}

    @abstractmethod
    def validate_config(self, config: dict) -> list[str]:
        """
        Validate provider configuration.

        Args:
            config: Configuration dictionary (decrypted)

        Returns:
            List of validation error messages (empty if valid)
        """
        pass

    @abstractmethod
    def send(
        self,
        config: dict,
        message: str,
        title: str | None = None,
        data: dict | None = None,
    ) -> NotificationResult:
        """
        Send a notification.

        Args:
            config: Provider configuration (decrypted)
            message: Notification message body
            title: Optional notification title
            data: Optional provider-specific data

        Returns:
            NotificationResult indicating success or failure
        """
        pass

    def test(self, config: dict) -> NotificationResult:
        """
        Send a test notification.

        Default implementation sends a standard test message.
        Override for provider-specific test behavior.

        Args:
            config: Provider configuration (decrypted)

        Returns:
            NotificationResult indicating success or failure
        """
        return self.send(
            config,
            message="This is a test notification from your alarm system.",
            title="Test Notification",
        )
