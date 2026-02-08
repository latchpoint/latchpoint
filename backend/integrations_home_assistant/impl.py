from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from config.domain_exceptions import GatewayError

logger = logging.getLogger(__name__)


GATEWAY_NAME = "Home Assistant"


class HomeAssistantAvailabilityError(GatewayError):
    gateway_name = GATEWAY_NAME


class HomeAssistantNotConfigured(HomeAssistantAvailabilityError):
    pass


class HomeAssistantNotReachable(HomeAssistantAvailabilityError):
    def __init__(self, error: str | None = None):
        """Wrap an optional low-level reachability error string."""
        self.error = error
        super().__init__(error or "Home Assistant is not reachable.")


@dataclass(frozen=True)
class HomeAssistantStatus:
    configured: bool
    reachable: bool
    base_url: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize status to a JSON-friendly dict for API responses."""
        return {
            "configured": self.configured,
            "reachable": self.reachable,
            "base_url": self.base_url,
            "error": self.error,
        }


def _ha_headers(token: str) -> dict[str, str]:
    """Return HTTP headers for Home Assistant REST API requests."""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _build_url(*, base_url: str, path: str) -> str:
    """Join `base_url` and an absolute Home Assistant API path."""
    base = (base_url or "").rstrip("/")
    return f"{base}{path}"


def get_status(
    *,
    base_url: str,
    token: str,
    get_client,
    urlopen,
    timeout_seconds: float = 2.0,
    logger_obj: logging.Logger | None = None,
) -> HomeAssistantStatus:
    """Return a non-raising status snapshot for the given Home Assistant connection settings."""
    log = logger_obj or logger
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        log.info("HA status: not configured (missing url/token)")
        return HomeAssistantStatus(configured=False, reachable=False, base_url=base_url or None)

    client = None
    try:
        client = get_client()
    except Exception:
        client = None

    if client is not None:
        try:
            log.debug("HA status: checking via homeassistant_api client.get_config() (base_url=%s)", base_url)
            client.get_config()
            log.info("HA status: reachable via client (base_url=%s)", base_url)
            return HomeAssistantStatus(configured=True, reachable=True, base_url=base_url)
        except Exception as exc:
            client_error = str(exc)
            log.warning(
                "HA status: client check failed; falling back to raw HTTP (base_url=%s, error=%s: %s)",
                base_url,
                exc.__class__.__name__,
                client_error,
            )
    else:
        client_error = None

    url = _build_url(base_url=base_url, path="/api/")
    request = Request(url, headers=_ha_headers(token), method="GET")
    try:
        log.debug("HA status: checking via raw HTTP GET %s (timeout=%ss)", url, timeout_seconds)
        with urlopen(request, timeout=timeout_seconds) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if 200 <= response.status < 300:
                if "application/json" not in content_type:
                    body_preview = response.read(256).decode("utf-8", errors="replace")
                    log.warning(
                        "HA status: unexpected content-type (status=%s, content_type=%s, body_preview=%r)",
                        response.status,
                        content_type or "unknown",
                        body_preview,
                    )
                    return HomeAssistantStatus(
                        configured=True,
                        reachable=False,
                        base_url=base_url,
                        error=f"Unexpected content-type from Home Assistant: {content_type or 'unknown'}",
                    )
                log.info("HA status: reachable via raw HTTP (base_url=%s)", base_url)
                return HomeAssistantStatus(configured=True, reachable=True, base_url=base_url)
            return HomeAssistantStatus(
                configured=True,
                reachable=False,
                base_url=base_url,
                error=f"Unexpected status: {response.status}",
            )
    except HTTPError as exc:
        try:
            content_type = (exc.headers.get("Content-Type") or "").lower()
        except Exception:
            content_type = ""
        try:
            body_preview = exc.read(256).decode("utf-8", errors="replace")
        except Exception:
            body_preview = ""
        log.warning(
            "HA status: HTTPError (base_url=%s, status=%s, content_type=%s, body_preview=%r)",
            base_url,
            exc.code,
            content_type or "unknown",
            body_preview,
        )
        return HomeAssistantStatus(
            configured=True,
            reachable=False,
            base_url=base_url,
            error=f"HTTP {exc.code}",
        )
    except URLError as exc:
        log.warning("HA status: URLError (base_url=%s, reason=%s)", base_url, exc.reason)
        return HomeAssistantStatus(
            configured=True,
            reachable=False,
            base_url=base_url,
            error=str(exc.reason),
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("HA status: unexpected error (base_url=%s)", base_url)
        return HomeAssistantStatus(
            configured=True,
            reachable=False,
            base_url=base_url,
            error=str(exc) if client_error is None else f"{exc}; client_error={client_error}",
        )


def ensure_available(
    *,
    base_url: str,
    token: str,
    get_client,
    urlopen,
    timeout_seconds: float = 2.0,
    logger_obj: logging.Logger | None = None,
) -> HomeAssistantStatus:
    """Validate that Home Assistant is configured and reachable; raise on failure."""
    status_obj = get_status(
        base_url=base_url,
        token=token,
        get_client=get_client,
        urlopen=urlopen,
        timeout_seconds=timeout_seconds,
        logger_obj=logger_obj,
    )
    if not status_obj.configured:
        raise HomeAssistantNotConfigured("Home Assistant is not configured.")
    if not status_obj.reachable:
        raise HomeAssistantNotReachable(status_obj.error)
    return status_obj


def list_entities(
    *,
    base_url: str,
    token: str,
    get_client,
    urlopen,
    timeout_seconds: float = 5.0,
    logger_obj: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """List entities from Home Assistant, using the client if available and falling back to raw HTTP."""
    log = logger_obj or logger
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        log.info("HA entities: not configured (missing url/token)")
        return []

    client = None
    try:
        client = get_client()
    except Exception:
        client = None

    if client is not None:
        try:
            log.debug("HA entities: fetching via homeassistant_api client.get_states() (base_url=%s)", base_url)
            states = client.get_states()
        except Exception:
            log.warning("HA entities: client.get_states() failed; falling back to raw HTTP (base_url=%s)", base_url)
            states = None
        if states is not None:
            entities: list[dict[str, Any]] = []
            for item in states:
                entity_id = getattr(item, "entity_id", None)
                state = getattr(item, "state", None)
                attributes = getattr(item, "attributes", None)
                last_changed = getattr(item, "last_changed", None)
                if not isinstance(entity_id, str) or not isinstance(state, str):
                    continue
                if not isinstance(attributes, dict):
                    attributes = {}

                zwavejs: dict[str, Any] = {}
                node_id = attributes.get("node_id") or attributes.get("nodeId") or attributes.get("nodeID")
                if isinstance(node_id, str) and node_id.isdigit():
                    node_id = int(node_id)
                if isinstance(node_id, int):
                    zwavejs["node_id"] = node_id
                home_id = attributes.get("home_id") or attributes.get("homeId") or attributes.get("homeID")
                if isinstance(home_id, str) and home_id.isdigit():
                    home_id = int(home_id)
                if isinstance(home_id, int):
                    zwavejs["home_id"] = home_id

                domain = entity_id.split(".", 1)[0] if "." in entity_id else "unknown"
                row: dict[str, Any] = {
                    "entity_id": entity_id,
                    "domain": domain,
                    "state": state,
                    "name": attributes.get("friendly_name") or entity_id,
                    "device_class": attributes.get("device_class"),
                    "unit_of_measurement": attributes.get("unit_of_measurement"),
                    "last_changed": last_changed,
                }
                if zwavejs:
                    row["zwavejs"] = zwavejs
                entities.append(row)
            return entities

    url = _build_url(base_url=base_url, path="/api/states")
    request = Request(url, headers=_ha_headers(token), method="GET")
    try:
        log.debug("HA entities: fetching via raw HTTP GET %s (timeout=%ss)", url, timeout_seconds)
        with urlopen(request, timeout=timeout_seconds) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            raw = response.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning(
                "HA entities: JSON decode error (content_type=%s, body_preview=%r)",
                content_type or "unknown",
                raw[:256],
            )
            raise RuntimeError(
                f"Home Assistant returned non-JSON response (content-type: {content_type or 'unknown'})."
            ) from exc
    except HTTPError as exc:
        try:
            content_type = (exc.headers.get("Content-Type") or "").lower()
        except Exception:
            content_type = ""
        try:
            body_preview = exc.read(256).decode("utf-8", errors="replace")
        except Exception:
            body_preview = ""
        log.warning(
            "HA entities: HTTPError (base_url=%s, status=%s, content_type=%s, body_preview=%r)",
            base_url,
            exc.code,
            content_type or "unknown",
            body_preview,
        )
        raise RuntimeError(f"Home Assistant returned HTTP {exc.code}.") from exc
    except URLError as exc:
        log.warning("HA entities: URLError (base_url=%s, reason=%s)", base_url, exc.reason)
        raise RuntimeError(f"Home Assistant request failed: {exc.reason}") from exc
    if not isinstance(payload, list):
        log.warning("HA entities: unexpected payload type %s", type(payload).__name__)
        return []

    entities: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        entity_id = item.get("entity_id")
        state = item.get("state")
        attributes = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        if not isinstance(entity_id, str) or not isinstance(state, str):
            continue

        zwavejs: dict[str, Any] = {}
        node_id = attributes.get("node_id") or attributes.get("nodeId") or attributes.get("nodeID")
        if isinstance(node_id, str) and node_id.isdigit():
            node_id = int(node_id)
        if isinstance(node_id, int):
            zwavejs["node_id"] = node_id
        home_id = attributes.get("home_id") or attributes.get("homeId") or attributes.get("homeID")
        if isinstance(home_id, str) and home_id.isdigit():
            home_id = int(home_id)
        if isinstance(home_id, int):
            zwavejs["home_id"] = home_id

        domain = entity_id.split(".", 1)[0] if "." in entity_id else "unknown"
        row: dict[str, Any] = {
            "entity_id": entity_id,
            "domain": domain,
            "state": state,
            "name": attributes.get("friendly_name") or entity_id,
            "device_class": attributes.get("device_class"),
            "unit_of_measurement": attributes.get("unit_of_measurement"),
            "last_changed": item.get("last_changed"),
        }
        if zwavejs:
            row["zwavejs"] = zwavejs
        entities.append(row)
    return entities


def call_service(
    *,
    base_url: str,
    token: str,
    get_client,
    urlopen,
    domain: str,
    service: str,
    target: dict[str, Any] | None = None,
    service_data: dict[str, Any] | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Call a Home Assistant service via client (preferred) or REST API fallback."""
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        raise RuntimeError("Home Assistant is not configured.")

    # Home Assistant REST API expects service fields at the top-level JSON body
    # (e.g. {"message": "...", "title": "..."}). The {"target": ..., "service_data": ...}
    # wrapper shape is used by the WebSocket call_service API, not the REST endpoint.
    payload: dict[str, Any] = {}
    if isinstance(target, dict):
        payload.update(target)
    if isinstance(service_data, dict):
        payload.update(service_data)

    client = None
    try:
        client = get_client()
    except Exception:
        client = None

    if client is not None:
        try:
            client.call_service(domain, service, **payload)
            return
        except Exception:
            pass

    url = _build_url(base_url=base_url, path=f"/api/services/{domain}/{service}")
    request = Request(url, headers=_ha_headers(token), method="POST", data=json.dumps(payload).encode("utf-8"))
    with urlopen(request, timeout=timeout_seconds) as response:
        if not (200 <= response.status < 300):
            raise RuntimeError(f"Unexpected status: {response.status}")


def list_services(
    *,
    base_url: str,
    token: str,
    urlopen,
    timeout_seconds: float = 5.0,
    logger_obj: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """
    Returns Home Assistant services payload (domain + services map).
    See: GET /api/services
    """
    log = logger_obj or logger
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        log.info("HA services: not configured (missing url/token)")
        return []

    url = _build_url(base_url=base_url, path="/api/services")
    request = Request(url, headers=_ha_headers(token), method="GET")
    try:
        log.debug("HA services: fetching via raw HTTP GET %s (timeout=%ss)", url, timeout_seconds)
        with urlopen(request, timeout=timeout_seconds) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            raw = response.read().decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning(
                "HA services: JSON decode error (content_type=%s, body_preview=%r)",
                content_type or "unknown",
                raw[:256],
            )
            raise RuntimeError(
                f"Home Assistant returned non-JSON response (content-type: {content_type or 'unknown'})."
            ) from exc
    except HTTPError as exc:
        try:
            content_type = (exc.headers.get("Content-Type") or "").lower()
        except Exception:
            content_type = ""
        try:
            body_preview = exc.read(256).decode("utf-8", errors="replace")
        except Exception:
            body_preview = ""
        log.warning(
            "HA services: HTTPError (base_url=%s, status=%s, content_type=%s, body_preview=%r)",
            base_url,
            exc.code,
            content_type or "unknown",
            body_preview,
        )
        raise RuntimeError(f"Home Assistant returned HTTP {exc.code}.") from exc
    except URLError as exc:
        log.warning("HA services: URLError (base_url=%s, reason=%s)", base_url, exc.reason)
        raise RuntimeError(f"Home Assistant request failed: {exc.reason}") from exc

    if not isinstance(payload, list):
        log.warning("HA services: unexpected payload type %s", type(payload).__name__)
        return []
    return [item for item in payload if isinstance(item, dict)]


def list_notify_services(
    *,
    base_url: str,
    token: str,
    urlopen,
    timeout_seconds: float = 5.0,
    logger_obj: logging.Logger | None = None,
) -> list[str]:
    """
    Returns a sorted list of notify services like: ["notify.notify", "notify.mobile_app_phone"].
    """
    rows = list_services(base_url=base_url, token=token, urlopen=urlopen, timeout_seconds=timeout_seconds, logger_obj=logger_obj)
    out: set[str] = set()
    for row in rows:
        if row.get("domain") != "notify":
            continue
        services = row.get("services")
        if not isinstance(services, dict):
            continue
        for service_name in services.keys():
            if isinstance(service_name, str) and service_name:
                out.add(f"notify.{service_name}")
    return sorted(out)
