from __future__ import annotations

"""
Home Assistant integration API surface.
"""

import logging
from urllib.request import urlopen

from integrations_home_assistant import impl
from integrations_home_assistant.connection import get_cached_connection, warm_up_cached_connection_if_needed

logger = logging.getLogger("integrations_home_assistant")

HomeAssistantAvailabilityError = impl.HomeAssistantAvailabilityError
HomeAssistantNotConfigured = impl.HomeAssistantNotConfigured
HomeAssistantNotReachable = impl.HomeAssistantNotReachable
HomeAssistantStatus = impl.HomeAssistantStatus


def _import_client():
    """Best-effort import of the Home Assistant API client, handling versioned import paths."""
    try:
        from homeassistant_api import Client as HomeAssistantClient  # type: ignore
    except ImportError:
        try:
            from homeassistant_api.client import Client as HomeAssistantClient  # type: ignore
        except ImportError:
            return None
    return HomeAssistantClient


def _get_client(*, base_url: str, token: str):
    """Instantiate a Home Assistant client if inputs are present and the dependency is installed."""
    client_cls = _import_client()
    if not client_cls:
        return None
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        return None
    return client_cls(base_url, token)


def _resolve_connection() -> tuple[str, str, float, str | None]:
    """
    Returns (base_url, token, connect_timeout_seconds, error).

    Connection settings are sourced from the active settings profile via the in-process cache.
    """

    warm_up_cached_connection_if_needed()
    cached = get_cached_connection()
    if cached is None:
        return "", "", 2.0, None
    if cached.error:
        return "", "", float(cached.connect_timeout_seconds or 2), cached.error
    if not cached.enabled:
        return "", "", float(cached.connect_timeout_seconds or 2), None
    return (
        str(cached.base_url or "").strip(),
        str(cached.token or "").strip(),
        float(cached.connect_timeout_seconds or 2),
        None,
    )


def get_status(*, timeout_seconds: float = 2.0) -> HomeAssistantStatus:
    """Return a non-raising status snapshot for the current active profile settings."""
    base_url, token, default_timeout, error = _resolve_connection()
    if error:
        return HomeAssistantStatus(
            configured=False,
            reachable=False,
            base_url=base_url or None,
            error=error,
        )
    return impl.get_status(
        base_url=base_url,
        token=token,
        get_client=lambda: _get_client(base_url=base_url, token=token),
        urlopen=urlopen,
        timeout_seconds=float(timeout_seconds or default_timeout),
        logger_obj=logger,
    )


def ensure_available(*, timeout_seconds: float = 2.0) -> HomeAssistantStatus:
    """Validate that Home Assistant is configured and reachable; raise on failure."""
    status_obj = get_status(timeout_seconds=timeout_seconds)
    if not status_obj.configured:
        raise HomeAssistantNotConfigured("Home Assistant is not configured.")
    if not status_obj.reachable:
        raise HomeAssistantNotReachable(getattr(status_obj, "error", None))
    return status_obj


def list_entities(*, timeout_seconds: float = 5.0) -> list[dict]:
    """List entities from Home Assistant, returning an empty list when not configured."""
    base_url, token, default_timeout, error = _resolve_connection()
    if error:
        return []
    return impl.list_entities(
        base_url=base_url,
        token=token,
        get_client=lambda: _get_client(base_url=base_url, token=token),
        urlopen=urlopen,
        timeout_seconds=float(timeout_seconds or default_timeout),
        logger_obj=logger,
    )


def list_notify_services(*, timeout_seconds: float = 5.0) -> list[str]:
    """List notify service names from Home Assistant, returning an empty list when not configured."""
    base_url, token, default_timeout, error = _resolve_connection()
    if error:
        return []
    return impl.list_notify_services(
        base_url=base_url,
        token=token,
        urlopen=urlopen,
        timeout_seconds=float(timeout_seconds or default_timeout),
        logger_obj=logger,
    )


def call_service(
    *,
    domain: str,
    service: str,
    target: dict | None = None,
    service_data: dict | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Call a Home Assistant service for the current active profile settings."""
    base_url, token, default_timeout, error = _resolve_connection()
    if error:
        raise RuntimeError(error)
    return impl.call_service(
        base_url=base_url,
        token=token,
        get_client=lambda: _get_client(base_url=base_url, token=token),
        urlopen=urlopen,
        domain=domain,
        service=service,
        target=target,
        service_data=service_data,
        timeout_seconds=float(timeout_seconds or default_timeout),
    )
