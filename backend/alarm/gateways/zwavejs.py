from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from integrations_zwavejs.manager import (
    ZwavejsConnectionManager,
    ZwavejsConnectionSettings,
    ZwavejsConnectionStatus,
    zwavejs_connection_manager,
)


class ZwavejsGateway(Protocol):
    def get_status(self) -> ZwavejsConnectionStatus:
        """Return the current Z-Wave JS connection status snapshot."""

        ...

    def apply_settings(self, *, settings_obj: ZwavejsConnectionSettings) -> None:
        """Apply runtime connection settings (typically from the active settings profile)."""

        ...

    def test_connection(self, *, settings_obj: ZwavejsConnectionSettings, timeout_seconds: float | None = None) -> None:
        """Attempt a short-lived connect/listen handshake to validate settings."""

        ...

    def ensure_connected(self, *, timeout_seconds: float = 5.0) -> None:
        """Block until the driver is ready or raise if it does not become ready within timeout."""

        ...

    def controller_get_state(self, *, timeout_seconds: float = 5.0) -> dict:
        """Return a controller state snapshot (nodes + controller metadata)."""

        ...

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0) -> list[dict]:
        """Return the node's defined value IDs as dicts suitable for API transport."""

        ...

    def node_get_value_metadata(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> dict:
        """Return metadata for the given value id on a node."""

        ...

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> object:
        """Return the current cached value for a node value id (no network I/O expected)."""

        ...

    def get_home_id(self) -> int | None:
        """Return the Z-Wave home id if connected, else `None`."""

        ...

    def set_value(
        self,
        *,
        node_id: int,
        endpoint: int,
        command_class: int,
        property: str | int,
        value: object,
        property_key: str | int | None = None,
    ) -> None:
        """Set a node value by value id components (write, waits for result)."""

        ...


@dataclass(frozen=True)
class DefaultZwavejsGateway:
    manager: ZwavejsConnectionManager = zwavejs_connection_manager

    def get_status(self) -> ZwavejsConnectionStatus:
        """Return the current Z-Wave JS connection status snapshot."""
        return self.manager.get_status()

    def apply_settings(self, *, settings_obj: ZwavejsConnectionSettings) -> None:
        """Apply runtime connection settings (typically from the active settings profile)."""
        self.manager.apply_settings(settings_obj=settings_obj)

    def test_connection(self, *, settings_obj: ZwavejsConnectionSettings, timeout_seconds: float | None = None) -> None:
        """Attempt a short-lived connect/listen handshake to validate settings."""
        self.manager.test_connection(settings_obj=settings_obj, timeout_seconds=timeout_seconds)

    def ensure_connected(self, *, timeout_seconds: float = 5.0) -> None:
        """Block until the driver is ready or raise if it does not become ready within timeout."""
        self.manager.ensure_connected(timeout_seconds=timeout_seconds)

    def controller_get_state(self, *, timeout_seconds: float = 5.0) -> dict:
        """Return a controller state snapshot (nodes + controller metadata)."""
        return self.manager.controller_get_state(timeout_seconds=timeout_seconds)

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0) -> list[dict]:
        """Return the node's defined value IDs as dicts suitable for API transport."""
        return self.manager.node_get_defined_value_ids(node_id=node_id, timeout_seconds=timeout_seconds)

    def node_get_value_metadata(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> dict:
        """Return metadata for the given value id on a node."""
        return self.manager.node_get_value_metadata(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)

    def node_get_value(self, *, node_id: int, value_id: dict, timeout_seconds: float = 5.0) -> object:
        """Return the current cached value for a node value id (no network I/O expected)."""
        return self.manager.node_get_value(node_id=node_id, value_id=value_id, timeout_seconds=timeout_seconds)

    def get_home_id(self) -> int | None:
        """Return the Z-Wave home id if connected, else `None`."""
        return self.manager.get_home_id()

    def set_value(
        self,
        *,
        node_id: int,
        endpoint: int,
        command_class: int,
        property: str | int,
        value: object,
        property_key: str | int | None = None,
    ) -> None:
        """Set a node value by value id components (write, waits for result)."""
        self.manager.set_value(
            node_id=node_id,
            endpoint=endpoint,
            command_class=command_class,
            property=property,
            value=value,
            property_key=property_key,
        )


default_zwavejs_gateway: ZwavejsGateway = DefaultZwavejsGateway()
