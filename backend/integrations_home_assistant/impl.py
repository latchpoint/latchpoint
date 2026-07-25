"""Home Assistant transport: mid-migration onto ``homeassistant_api`` (ADR-0105).

- ``get_status`` / ``ensure_available`` go through the pinned ``homeassistant_api`` client
  (Phase 1). Reachability only — no row shapes cross this boundary.
- ``list_entities``, ``call_service``, ``list_services``, ``list_service_catalog`` and
  ``list_notify_services`` are still hand-rolled REST over ``urllib``. They move in
  Phases 2-4, each behind its own shape-parity audit.

Earlier revisions carried ``homeassistant_api`` branches that were meant to be preferred,
with REST as a fallback — but not one of them ever worked, and each failure was swallowed by
a broad ``except``, so REST was always the real path:

- ``call_service`` called ``client.call_service()``, which does not exist (the library
  exposes ``trigger_service``), so it raised ``AttributeError`` every time. Removed in #78.
- ``get_status`` and ``list_entities`` passed our bare ``base_url`` as the library's
  ``api_url``. That argument is used verbatim as the endpoint prefix, so ``get_config()``
  requested ``{base_url}/config`` — Home Assistant's Single Page App route, which answers
  200 with ``text/html``. The library has no processor for that mimetype, so every call
  raised ``ProcessorNotFoundError`` and logged a warning on the way to REST. Removed in #86.

``_api_url`` is why that defect cannot come back: the client is only ever constructed with
the ``/api``-suffixed URL, and a test pins it.

Correcting that URL *without* a migration was tried and rejected (#85): it would have
activated a second, never-executed parser in ``list_entities`` whose ``last_changed`` is a
``datetime`` where the REST path yields an ISO string, silently changing the shape of rows
that feed ``sync_entity_states`` and the ``Entity`` table the alarm's sensors read. That is
also why ``list_entities`` migrates last rather than first.

There is deliberately **no** REST fallback behind the migrated path. A preferred-plus-fallback
pair is precisely what hid all three dead branches above, so each phase leaves exactly one
transport per function.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from homeassistant_api import Client
from homeassistant_api.errors import HomeassistantAPIError

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


def _api_url(base_url: str) -> str:
    """Return the REST API endpoint prefix that ``homeassistant_api`` must be built with.

    The library's first constructor argument is named ``api_url`` and is used verbatim as the
    endpoint prefix — it never inserts ``/api``. Settings store the browser-facing base URL
    (``http://ha.local:8123``), so the suffix has to be added here; without it every call
    lands on Home Assistant's Single Page App route and comes back as ``text/html``. That was
    the defect behind the dead client branches (see the module docstring), so it is pinned by
    a test. A ``base_url`` that already ends in ``/api`` is not doubled, and the suffix is
    normalized to lower case — Home Assistant's route is ``/api/``, so echoing back a ``/API``
    the operator typed would 404 the reachability check.
    """
    base = (base_url or "").strip().rstrip("/")
    if base.lower().endswith("/api"):
        return f"{base[:-4]}/api/"
    return f"{base}/api/"


def _body_preview(response: Any, *, limit: int = 256) -> str:
    """Best-effort short preview of a response body, for diagnostics only."""
    try:
        text = getattr(response, "text", None)
    except Exception:  # pragma: no cover - defensive
        return ""
    return text[:limit] if isinstance(text, str) else ""


class _StatusClient(Client):
    """``homeassistant_api`` client that remembers the last response it processed.

    The library maps HTTP failures onto exception *types* — 401 to ``UnauthorizedError``,
    404 to ``EndpointNotFoundError``, 5xx to ``InternalServerError`` — and carries neither
    the numeric status code nor the content type on the exception. ``get_status`` has to
    report both, because ``"HTTP 401"`` and ``"Unexpected content-type from Home Assistant:
    ..."`` are the strings the UI and the API have always returned. ``response_logic`` is the
    single funnel every request passes through, and it runs before the status check raises,
    so it is the one place that sees every response.
    """

    def __init__(self, *, api_url: str, token: str, timeout_seconds: float) -> None:
        # The timeout has to be a global request kwarg: ``check_api_running()`` takes no
        # arguments, so there is no per-call seam to thread it through, and
        # ``global_request_kwargs`` is what the client forwards to the session on every
        # request. Verified to bound the call at the socket layer (ADR-0105 AC-2).
        super().__init__(api_url, token, global_request_kwargs={"timeout": timeout_seconds})
        self.last_status_code: int | None = None
        self.last_content_type: str = ""
        self.last_body_preview: str = ""

    def response_logic(self, response: Any) -> Any:
        """Record the response, then hand it to the library's own processing unchanged."""
        status_code = getattr(response, "status_code", None)
        headers = getattr(response, "headers", None) or {}
        content_type = str(headers.get("content-type") or "").lower()
        self.last_status_code = status_code if isinstance(status_code, int) else None
        self.last_content_type = content_type
        # Mirror the raw-HTTP implementation: only read the body on the paths that report it.
        if self.last_status_code is None or not _is_success(self.last_status_code) or not _is_json(content_type):
            self.last_body_preview = _body_preview(response)
        return Client.response_logic(response)

    def close(self) -> None:
        """Close the underlying HTTP session.

        The library only closes it from ``__exit__``, and its ``__enter__`` calls
        ``check_api_running()`` — so using it as a context manager would double the request.
        """
        self._session.close()


def _is_success(status_code: int) -> bool:
    """Return True for a 2xx HTTP status code."""
    return 200 <= status_code < 300


def _is_json(content_type: str) -> bool:
    """Return True when a (lowercased) content-type header advertises JSON."""
    return "application/json" in content_type


def _build_status_client(*, api_url: str, token: str, timeout_seconds: float) -> _StatusClient:
    """Build the client used for reachability checks. Patch point for tests that go via a view."""
    return _StatusClient(api_url=api_url, token=token, timeout_seconds=timeout_seconds)


def _close_quietly(client: Any) -> None:
    """Release a client's HTTP session without letting cleanup mask the status result."""
    close = getattr(client, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:  # pragma: no cover - defensive
        logger.debug("HA status: closing client session failed", exc_info=True)


def _unreachable(
    *,
    base_url: str,
    client: Any,
    exc: BaseException,
    log: logging.Logger,
) -> HomeAssistantStatus:
    """Build the unreachable status for a failed reachability check.

    The error string is derived from the response the client actually saw rather than from the
    exception type, which keeps it identical to what the raw-HTTP implementation reported:
    ``HTTP <code>`` for a non-2xx answer, ``Unexpected content-type ...`` for a 2xx answer we
    cannot parse. When nothing was received at all — connect refused, DNS, TLS, timeout — the
    low-level reason is passed through the way ``URLError.reason`` used to be.
    """
    status_code = getattr(client, "last_status_code", None)
    content_type = getattr(client, "last_content_type", "") or ""
    body_preview = getattr(client, "last_body_preview", "") or ""

    if isinstance(status_code, int) and not _is_success(status_code):
        log.warning(
            "HA status: HTTP error (base_url=%s, status=%s, content_type=%s, body_preview=%r)",
            base_url,
            status_code,
            content_type or "unknown",
            body_preview,
        )
        return HomeAssistantStatus(configured=True, reachable=False, base_url=base_url, error=f"HTTP {status_code}")

    if isinstance(status_code, int) and not _is_json(content_type):
        log.warning(
            "HA status: unexpected content-type (status=%s, content_type=%s, body_preview=%r)",
            status_code,
            content_type or "unknown",
            body_preview,
        )
        return HomeAssistantStatus(
            configured=True,
            reachable=False,
            base_url=base_url,
            error=f"Unexpected content-type from Home Assistant: {content_type or 'unknown'}",
        )

    log.warning(
        "HA status: unreachable (base_url=%s, error=%s: %s)",
        base_url,
        type(exc).__name__,
        exc,
    )
    return HomeAssistantStatus(configured=True, reachable=False, base_url=base_url, error=str(exc))


def get_status(
    *,
    base_url: str,
    token: str,
    timeout_seconds: float = 2.0,
    logger_obj: logging.Logger | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> HomeAssistantStatus:
    """Return a non-raising status snapshot for the given Home Assistant connection settings.

    Reachability is ``homeassistant_api``'s ``check_api_running()`` (``GET {base_url}/api/``).
    ``base_url`` is echoed back exactly as configured; only the client is built from the
    ``/api``-suffixed form.
    """
    log = logger_obj or logger
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        log.info("HA status: not configured (missing url/token)")
        return HomeAssistantStatus(configured=False, reachable=False, base_url=base_url or None)

    api_url = _api_url(base_url)
    factory = client_factory or _build_status_client
    client: Any = None
    try:
        log.debug("HA status: checking via client GET %s (timeout=%ss)", api_url, timeout_seconds)
        client = factory(api_url=api_url, token=token, timeout_seconds=timeout_seconds)
        running = client.check_api_running()
    except (HomeassistantAPIError, OSError, ValueError, TypeError) as exc:
        # HomeassistantAPIError covers the library's own failures: RequestTimeoutError, the
        # per-status-code errors, and ProcessorNotFoundError/MalformedDataError for a body it
        # cannot parse. OSError covers every transport failure underneath it — niquests'
        # RequestException subclasses OSError, exactly as urllib's URLError did — so connect
        # refused, DNS, TLS and socket timeouts all land here. ValueError is the library
        # rejecting a base_url with no http(s) scheme, and TypeError is its "expected dict
        # response" guard when Home Assistant answers 2xx with a non-object body.
        return _unreachable(base_url=base_url, client=client, exc=exc, log=log)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("HA status: unexpected error (base_url=%s)", base_url)
        return HomeAssistantStatus(configured=True, reachable=False, base_url=base_url, error=str(exc))
    finally:
        _close_quietly(client)

    if not running:
        # 2xx JSON, but not Home Assistant's ``{"message": "API running."}``. The raw-HTTP
        # implementation never read the body and would have called this reachable; the library
        # checks it, and an unrecognised answer on /api/ is reported rather than assumed good.
        log.warning(
            "HA status: API did not report running (base_url=%s, status=%s)",
            base_url,
            getattr(client, "last_status_code", None),
        )
        return HomeAssistantStatus(
            configured=True,
            reachable=False,
            base_url=base_url,
            error="Home Assistant did not report the API as running.",
        )

    log.info("HA status: reachable (base_url=%s)", base_url)
    return HomeAssistantStatus(configured=True, reachable=True, base_url=base_url)


def ensure_available(
    *,
    base_url: str,
    token: str,
    timeout_seconds: float = 2.0,
    logger_obj: logging.Logger | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> HomeAssistantStatus:
    """Validate that Home Assistant is configured and reachable; raise on failure."""
    status_obj = get_status(
        base_url=base_url,
        token=token,
        timeout_seconds=timeout_seconds,
        logger_obj=logger_obj,
        client_factory=client_factory,
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
    urlopen,
    timeout_seconds: float = 5.0,
    logger_obj: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """List entities from Home Assistant via the REST API."""
    log = logger_obj or logger
    base_url = (base_url or "").strip()
    token = (token or "").strip()
    if not base_url or not token:
        log.info("HA entities: not configured (missing url/token)")
        return []

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

    REST is this module's single transport for every Home Assistant call — see the module
    docstring for why the ``homeassistant_api`` client branches were removed. HA's service
    endpoint returns the list of states it changed, so a call that changes nothing is logged
    as a likely no-op (e.g. an optimistic or script-backed light that never actuated).
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
