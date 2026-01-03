from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from urllib.request import urlopen

from integrations_home_assistant import impl as ha_impl
from integrations_home_assistant.connection import get_cached_connection, warm_up_cached_connection_if_needed

from config.domain_exceptions import GatewayError

GATEWAY_NAME = "Home Assistant"


class HomeAssistantGatewayError(GatewayError):
    gateway_name = GATEWAY_NAME


class HomeAssistantNotConfigured(HomeAssistantGatewayError):
    pass


class HomeAssistantNotReachable(HomeAssistantGatewayError):
    def __init__(self, error: str | None = None):
        """Wrap an optional low-level reachability error string."""
        self.error = error
        super().__init__(error or "Home Assistant is not reachable.")


class HomeAssistantGateway(Protocol):
    def get_status(self, *, timeout_seconds: float = 2.0) -> ha_impl.HomeAssistantStatus:
        """Return a non-raising status snapshot for the current Home Assistant connection settings."""

        ...

    def ensure_available(self, *, timeout_seconds: float = 2.0) -> ha_impl.HomeAssistantStatus:
        """Assert the connection is configured and reachable; raise gateway errors on failure."""

        ...

    def list_entities(self, *, timeout_seconds: float = 5.0) -> list[dict[str, Any]]:
        """List entities from Home Assistant."""

        ...

    def list_notify_services(self, *, timeout_seconds: float = 5.0) -> list[str]:
        """List notify service names from Home Assistant."""

        ...

    def call_service(
        self,
        *,
        domain: str,
        service: str,
        target: dict[str, Any] | None = None,
        service_data: dict[str, Any] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        """Call a Home Assistant service."""

        ...


@dataclass(frozen=True)
class DefaultHomeAssistantGateway:
    """
    Profile-aware adapter around the Home Assistant integration implementation.

    Resolution order:
    - Use the cached `home_assistant_connection` settings (populated from the active profile).
    - If no cached settings are available, treat Home Assistant as not configured.
    """

    def _import_client(self):
        """Best-effort import of the Home Assistant API client, handling versioned import paths."""
        try:
            from homeassistant_api import Client as HomeAssistantClient  # type: ignore
        except ImportError:
            try:
                from homeassistant_api.client import Client as HomeAssistantClient  # type: ignore
            except ImportError:
                return None
        return HomeAssistantClient

    def _get_client(self, *, base_url: str, token: str):
        """Instantiate a Home Assistant client if inputs are present and the dependency is installed."""
        client_cls = self._import_client()
        if not client_cls:
            return None
        base_url = (base_url or "").strip()
        token = (token or "").strip()
        if not base_url or not token:
            return None
        return client_cls(base_url, token)

    def _resolve_connection(self) -> tuple[str, str, float, str | None]:
        """
        Returns (base_url, token, connect_timeout_seconds, error).
        """

        try:
            cached = get_cached_connection()
            if cached is None:
                warm_up_cached_connection_if_needed()
                cached = get_cached_connection()
            if cached is not None:
                if not cached.enabled:
                    return "", "", float(cached.connect_timeout_seconds or 2), cached.error
                return (
                    cached.base_url,
                    cached.token,
                    float(cached.connect_timeout_seconds or 2),
                    cached.error,
                )
        except Exception:
            # Best-effort: never fail gateway resolution because cache access failed.
            pass

        return "", "", 2.0, None

    def get_status(self, *, timeout_seconds: float = 2.0) -> ha_impl.HomeAssistantStatus:
        """Return a non-raising connectivity/status snapshot for the current active profile settings."""
        base_url, token, default_timeout, error = self._resolve_connection()
        if error:
            return ha_impl.HomeAssistantStatus(
                configured=False,
                reachable=False,
                base_url=base_url or None,
                error=error,
            )
        return ha_impl.get_status(
            base_url=base_url,
            token=token,
            get_client=lambda: self._get_client(base_url=base_url, token=token),
            urlopen=urlopen,
            timeout_seconds=float(timeout_seconds or default_timeout),
        )

    def ensure_available(self, *, timeout_seconds: float = 2.0) -> ha_impl.HomeAssistantStatus:
        """Validate that Home Assistant is configured and reachable; raise typed gateway errors on failure."""
        try:
            base_url, token, default_timeout, error = self._resolve_connection()
            if error:
                raise HomeAssistantNotConfigured(error)
            return ha_impl.ensure_available(
                base_url=base_url,
                token=token,
                get_client=lambda: self._get_client(base_url=base_url, token=token),
                urlopen=urlopen,
                timeout_seconds=float(timeout_seconds or default_timeout),
            )
        except ha_impl.HomeAssistantNotConfigured as exc:
            raise HomeAssistantNotConfigured(str(exc) or "Home Assistant is not configured.") from exc
        except ha_impl.HomeAssistantNotReachable as exc:
            raise HomeAssistantNotReachable(getattr(exc, "error", None)) from exc

    def list_entities(self, *, timeout_seconds: float = 5.0) -> list[dict[str, Any]]:
        """List entities from Home Assistant (requires configured connection)."""
        base_url, token, _default_timeout, error = self._resolve_connection()
        if error:
            raise HomeAssistantNotConfigured(error)
        return ha_impl.list_entities(
            base_url=base_url,
            token=token,
            get_client=lambda: self._get_client(base_url=base_url, token=token),
            urlopen=urlopen,
            timeout_seconds=timeout_seconds,
        )

    def list_notify_services(self, *, timeout_seconds: float = 5.0) -> list[str]:
        """List notify services from Home Assistant (requires configured connection)."""
        base_url, token, _default_timeout, error = self._resolve_connection()
        if error:
            raise HomeAssistantNotConfigured(error)
        return ha_impl.list_notify_services(
            base_url=base_url,
            token=token,
            urlopen=urlopen,
            timeout_seconds=timeout_seconds,
        )

    def call_service(
        self,
        *,
        domain: str,
        service: str,
        target: dict[str, Any] | None = None,
        service_data: dict[str, Any] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        """Call a Home Assistant service (requires configured connection)."""
        base_url, token, _default_timeout, error = self._resolve_connection()
        if error:
            raise HomeAssistantNotConfigured(error)
        return ha_impl.call_service(
            base_url=base_url,
            token=token,
            get_client=lambda: self._get_client(base_url=base_url, token=token),
            urlopen=urlopen,
            domain=domain,
            service=service,
            target=target,
            service_data=service_data,
            timeout_seconds=timeout_seconds,
        )


default_home_assistant_gateway = DefaultHomeAssistantGateway()
