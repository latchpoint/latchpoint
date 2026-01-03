from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from transports_mqtt.manager import (
    MqttConnectionManager,
    MqttConnectionSettings,
    MqttConnectionStatus,
    mqtt_connection_manager,
)


class MqttGateway(Protocol):
    def get_status(self) -> MqttConnectionStatus:
        """Return the current connection status snapshot."""

        ...

    def apply_settings(self, *, settings: MqttConnectionSettings) -> None:
        """Apply runtime connection settings."""

        ...

    def test_connection(self, *, settings: MqttConnectionSettings, timeout_seconds: float | None = None) -> None:
        """Attempt a short-lived connection to validate settings."""

        ...


@dataclass(frozen=True)
class DefaultMqttGateway:
    manager: MqttConnectionManager = mqtt_connection_manager

    def get_status(self) -> MqttConnectionStatus:
        """Return the current connection status snapshot."""
        return self.manager.get_status()

    def apply_settings(self, *, settings: MqttConnectionSettings) -> None:
        """Apply runtime connection settings."""
        self.manager.apply_settings(settings=settings)

    def test_connection(self, *, settings: MqttConnectionSettings, timeout_seconds: float | None = None) -> None:
        """Attempt a short-lived connection to validate settings."""
        self.manager.test_connection(settings=settings, timeout_seconds=timeout_seconds)


default_mqtt_gateway: MqttGateway = DefaultMqttGateway()
