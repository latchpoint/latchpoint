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

# HA service-call target keys are singular (``entity_id``) even when the value is a list.
# The rules builder UI models the entity target as ``entityIds``, which the frontend
# snake-cases to ``entity_ids`` on the wire (see frontend ActionsEditor + services/api.ts).
# Without this remap HA rejects the unknown key with HTTP 400 and the service call
# (e.g. ``lock.lock``) silently does nothing. Scoped to entity targets — all the UI emits.
_HA_TARGET_KEY_ALIASES = {
    "entity_ids": "entity_id",
    "entityIds": "entity_id",
    "entityId": "entity_id",
}


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


def build_client_api_url(base_url: str) -> str:
    """Return the ``api_url`` to hand `homeassistant_api.Client`, given our stored base URL.

    The library's first constructor argument is named ``api_url`` and it is used verbatim
    as the prefix for every endpoint path — it never inserts ``/api`` itself. Passing our
    bare ``base_url`` therefore aimed the client at Home Assistant's *frontend*: a
    ``get_config()`` became ``GET {base_url}/config``, which is a Single Page App route
    that answers 200 with ``text/html``, so the library raised
    ``ProcessorNotFoundError: No response processor found for mimetype 'text/html'`` on
    every call and every request silently fell back to raw HTTP.

    Settings hold the browser-facing base URL (e.g. ``http://ha.local:8123``), which is
    what the raw-HTTP path wants, so the ``/api`` suffix is added here rather than stored.
    A ``base_url`` that already ends in ``/api`` is accepted and not doubled.
    """
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api"):
        return base
    return f"{base}/api"


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


def _read_changed_states(response: Any) -> list[Any] | None:
    """Best-effort parse of HA's service-call response body (the list of states it changed).

    Returns the parsed list, or ``None`` when the body is unavailable/unparseable — so callers can
    tell "changed nothing" apart from "don't know".
    """
    read = getattr(response, "read", None)
    if not callable(read):
        return None
    try:
        raw = read().decode("utf-8")
    except Exception:
        return None
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, list) else None


def call_service(
    *,
    base_url: str,
    token: str,
    urlopen,
    domain: str,
    service: str,
    target: dict[str, Any] | None = None,
    service_data: dict[str, Any] | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Call a Home Assistant service via the REST API.

    We POST directly rather than via the ``homeassistant_api`` client: its ``Client`` exposes
    ``trigger_service`` (not ``call_service``), so the old client branch here raised ``AttributeError``
    on every call and silently fell through to REST anyway. HA's service endpoint returns the list of
    states it changed, so a call that changes nothing is logged as a likely no-op (e.g. an optimistic
    or script-backed light that never actuated).
    """
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        raise RuntimeError("Home Assistant is not configured.")

    # Home Assistant REST API expects service fields at the top-level JSON body
    # (e.g. {"message": "...", "title": "..."}). The {"target": ..., "service_data": ...}
    # wrapper shape is used by the WebSocket call_service API, not the REST endpoint.
    payload: dict[str, Any] = {}
    if isinstance(target, dict):
        for key, value in target.items():
            payload[_HA_TARGET_KEY_ALIASES.get(key, key)] = value
    if isinstance(service_data, dict):
        payload.update(service_data)

    url = _build_url(base_url=base_url, path=f"/api/services/{domain}/{service}")
    request = Request(url, headers=_ha_headers(token), method="POST", data=json.dumps(payload).encode("utf-8"))
    with urlopen(request, timeout=timeout_seconds) as response:
        status = getattr(response, "status", 200)
        if not (200 <= status < 300):
            raise RuntimeError(f"Unexpected status: {status}")
        changed_states = _read_changed_states(response)

    # Only flag calls that explicitly targeted entities: a 0-change response there is the fingerprint
    # of a silent no-op (e.g. an optimistic/script-backed light that didn't actuate). Targetless
    # calls such as ``notify.*`` legitimately change no states, so they must not warn.
    if changed_states is not None and not changed_states and payload.get("entity_id"):
        logger.warning(
            "HA service %s.%s changed 0 states (possible no-op; entity_id=%s)",
            domain,
            service,
            payload.get("entity_id"),
        )


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


def _slim_service_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """
    Slim a service's ``fields`` map to the keys the rules-builder form needs.

    HA groups some fields into collapsed sections (entries with a nested
    ``fields`` dict and no ``selector``, e.g. light.turn_on's advanced_fields);
    those are hoisted so the result is a flat field map.
    """
    out: dict[str, Any] = {}
    for field_name, spec in fields.items():
        if not isinstance(field_name, str) or not field_name or not isinstance(spec, dict):
            continue
        nested = spec.get("fields")
        if isinstance(nested, dict) and "selector" not in spec:
            out.update(_slim_service_fields(nested))
            continue
        slim_keys = ("name", "description", "required", "example", "default", "selector")
        out[field_name] = {key: spec[key] for key in slim_keys if key in spec}
    return out


def list_service_catalog(
    *,
    base_url: str,
    token: str,
    urlopen,
    timeout_seconds: float = 5.0,
    logger_obj: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """
    Returns a flat, slimmed service catalog for the rules-builder action picker (ADR-0101):
    [{domain, service, name, description, fields, target?}], sorted by domain.service.
    """
    rows = list_services(
        base_url=base_url, token=token, urlopen=urlopen, timeout_seconds=timeout_seconds, logger_obj=logger_obj
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        domain = row.get("domain")
        services = row.get("services")
        if not isinstance(domain, str) or not domain or not isinstance(services, dict):
            continue
        for service_name, spec in services.items():
            if not isinstance(service_name, str) or not service_name:
                continue
            if not isinstance(spec, dict):
                spec = {}
            name = spec.get("name")
            description = spec.get("description")
            fields = spec.get("fields")
            entry: dict[str, Any] = {
                "domain": domain,
                "service": service_name,
                "name": name if isinstance(name, str) else "",
                "description": description if isinstance(description, str) else "",
                "fields": _slim_service_fields(fields) if isinstance(fields, dict) else {},
            }
            target = spec.get("target")
            if isinstance(target, dict):
                entry["target"] = target
            out.append(entry)
    out.sort(key=lambda item: (item["domain"], item["service"]))
    return out


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
    rows = list_services(
        base_url=base_url, token=token, urlopen=urlopen, timeout_seconds=timeout_seconds, logger_obj=logger_obj
    )
    out: set[str] = set()
    for row in rows:
        if row.get("domain") != "notify":
            continue
        services = row.get("services")
        if not isinstance(services, dict):
            continue
        for service_name in services:
            if isinstance(service_name, str) and service_name:
                out.add(f"notify.{service_name}")
    return sorted(out)
