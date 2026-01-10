from __future__ import annotations

import asyncio
import contextlib
import concurrent.futures
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, TypedDict
from urllib.parse import urlparse

from django.conf import settings as django_settings

from config.domain_exceptions import GatewayError, GatewayValidationError

GATEWAY_NAME = "Z-Wave JS"


class ZwavejsGatewayError(GatewayError):
    gateway_name = GATEWAY_NAME


class ZwavejsNotConfigured(ZwavejsGatewayError):
    pass


class ZwavejsNotReachable(ZwavejsGatewayError):
    def __init__(self, error: str | None = None):
        """Wrap an optional low-level reachability error string."""
        self.error = error
        super().__init__(error or "Z-Wave JS server is not reachable.")


class ZwavejsClientUnavailable(ZwavejsGatewayError):
    pass


class ZwavejsNotConnected(ZwavejsGatewayError):
    pass


class ZwavejsCommandValidationError(GatewayValidationError):
    gateway_name = GATEWAY_NAME


class ZwavejsCommandError(ZwavejsGatewayError):
    pass


class ZwavejsConnectionSettings(TypedDict, total=False):
    enabled: bool
    ws_url: str
    api_token: str
    connect_timeout_seconds: float
    reconnect_min_seconds: int
    reconnect_max_seconds: int


@dataclass(frozen=True)
class ZwavejsConnectionStatus:
    configured: bool
    enabled: bool
    connected: bool
    home_id: int | None = None
    last_connect_at: datetime | None = None
    last_disconnect_at: datetime | None = None
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize status to a JSON-friendly dict for API responses."""
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "connected": self.connected,
            "home_id": self.home_id,
            "last_connect_at": self.last_connect_at.isoformat() if self.last_connect_at else None,
            "last_disconnect_at": self.last_disconnect_at.isoformat() if self.last_disconnect_at else None,
            "last_error": self.last_error,
        }


def _now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def _is_configured(settings_obj: ZwavejsConnectionSettings) -> bool:
    """Return True if required connection settings are present and syntactically valid."""
    ws_url = (settings_obj.get("ws_url") or "").strip()
    if not ws_url:
        return False
    parsed = urlparse(ws_url)
    return parsed.scheme in {"ws", "wss"} and bool(parsed.hostname)


def _is_testing_disabled() -> bool:
    """Return True if integration I/O is disabled for tests (ADR 0010-style opt-in)."""
    # Mirror the HA approach (ADR 0010): disable external integration during tests by default.
    return bool(getattr(django_settings, "IS_TESTING", False)) and not bool(
        getattr(django_settings, "ALLOW_ZWAVEJS_IN_TESTS", False)
    )


def _validate_ws_url(ws_url: str) -> None:
    """Validate `ws_url` and raise `ZwavejsNotConfigured` with a helpful message on failure."""
    parsed = urlparse(ws_url)
    if parsed.scheme not in {"ws", "wss"}:
        raise ZwavejsNotConfigured("Z-Wave JS ws_url must start with ws:// or wss://.")
    if not parsed.hostname:
        raise ZwavejsNotConfigured("Z-Wave JS ws_url must include a hostname.")


def _backoff_seconds(*, attempt: int, min_seconds: int, max_seconds: int) -> float:
    """Compute exponential backoff seconds with min/max bounds."""
    if min_seconds < 0:
        min_seconds = 0
    if max_seconds < 0:
        max_seconds = 0
    if max_seconds and min_seconds and max_seconds < min_seconds:
        max_seconds = min_seconds

    sleep_s = float(min_seconds) * (2 ** min(attempt, 10))
    return float(min(max_seconds or sleep_s, max(min_seconds, sleep_s)))


def _import_zwavejs_client():
    """Import zwave-js-server client dependencies, returning `None` if not installed."""
    try:
        import aiohttp
        from zwave_js_server.client import Client
        from zwave_js_server.model.value import _get_value_id_str_from_dict

        return aiohttp, Client, _get_value_id_str_from_dict
    except Exception:
        return None


def _value_id_dict_from_value_data(value_data: dict[str, Any]) -> dict[str, Any]:
    """Extract a stable value-id dict from zwave-js value metadata for API transport."""
    out: dict[str, Any] = {
        "commandClass": value_data.get("commandClass"),
        "property": value_data.get("property"),
    }
    if "endpoint" in value_data and value_data.get("endpoint") is not None:
        out["endpoint"] = value_data.get("endpoint")
    if "propertyKey" in value_data and value_data.get("propertyKey") is not None:
        out["propertyKey"] = value_data.get("propertyKey")
    return out


class ZwavejsConnectionManager:
    """
    zwave-js-server connection manager (via `zwave-js-server-python`).

    Matches Home Assistant semantics:
    - Connect and validate server version/schema.
    - Initialize and start listening.
    - Consider the driver "ready" only after the initial full state dump is received.
    """

    def __init__(self) -> None:
        """Initialize manager state (no network I/O)."""
        self._lock = threading.Lock()
        self._settings: ZwavejsConnectionSettings = {}
        self._connected = False
        self._driver_ready = False
        self._home_id: int | None = None
        self._last_connect_at: datetime | None = None
        self._last_disconnect_at: datetime | None = None
        self._last_error: str | None = None
        self._logger = logging.getLogger(__name__)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        self._aiohttp_session = None
        self._client = None
        self._driver_ready_event = threading.Event()
        self._event_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._attached_node_ids: set[int] = set()
        self._event_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="zwavejs-events")

    def register_event_listener(self, _listener: Callable[[dict[str, Any]], None]) -> None:
        """
        Register a best-effort raw-event listener.

        The callback is invoked from the Z-Wave JS background thread (not the Django main thread).
        """

        if not callable(_listener):
            return
        with self._lock:
            self._event_listeners.append(_listener)

    def _emit_event(self, msg: dict[str, Any]) -> None:
        """Invoke all registered listeners with the given message (best-effort)."""
        listeners: tuple[Callable[[dict[str, Any]], None], ...]
        with self._lock:
            listeners = tuple(self._event_listeners)
        self._logger.debug("zwavejs dispatch listeners=%s", len(listeners))
        for listener in listeners:
            try:
                listener(msg)
            except Exception:
                continue

        # Notify dispatcher if this is a value update (ADR 0057)
        self._maybe_notify_dispatcher(msg)

    def _maybe_notify_dispatcher(self, msg: dict[str, Any]) -> None:
        """Notify the dispatcher of Z-Wave JS value changes (ADR 0057)."""
        try:
            from alarm.dispatcher import notify_entities_changed

            event = msg.get("event", {})
            if not isinstance(event, dict):
                return

            event_name = event.get("event")
            if event_name not in ("value updated", "value added", "value notification"):
                return

            # Extract node_id and value_id to build entity ID
            node_id = event.get("nodeId")
            args = event.get("args", {})
            if not isinstance(args, dict):
                return

            value_id = args.get("valueId", {})
            if not isinstance(value_id, dict):
                return

            with self._lock:
                home_id = self._home_id

            # Check for None specifically since node_id 0 can be valid in some Z-Wave networks
            if node_id is None or home_id is None:
                return

            entity_id = build_zwavejs_entity_id(home_id=home_id, node_id=node_id, value_id=value_id)
            from django.utils import timezone as dj_timezone

            notify_entities_changed(source="zwavejs", entity_ids=[entity_id], changed_at=dj_timezone.now())

        except Exception as exc:
            self._logger.debug("Dispatcher notification failed: %s", exc)

    def _coerce_event_message(self, event: Any) -> dict[str, Any] | None:
        """
        Attempt to coerce various zwave-js-server-python event shapes into a dict.

        Keep the outer `{"event": ...}` envelope when possible since some consumers historically
        expected that structure.
        """

        try:
            if isinstance(event, dict):
                payload: dict[str, Any] = event
            elif hasattr(event, "data"):
                payload = dict(getattr(event, "data") or {})
            elif hasattr(event, "__dict__"):
                payload = dict(getattr(event, "__dict__") or {})
            else:
                payload = {"value": event}
        except Exception:
            return None

        if "event" in payload and isinstance(payload.get("event"), dict):
            return payload
        return {"event": payload}

    def _sanitize_event_for_log(self, msg: dict[str, Any]) -> dict[str, Any]:
        """
        Redact sensitive payload fields (notably keypad PIN codes in Entry Control notifications).
        """

        try:
            event = msg.get("event")
            if not isinstance(event, dict):
                return {"event": type(event).__name__}
            out = dict(event)
            # Drop non-serializable objects and avoid leaking sensitive info via their repr().
            for key in ("node", "notification"):
                if key in out:
                    out[key] = f"<{type(out[key]).__name__}>"
            args = out.get("args")
            if isinstance(args, dict):
                args_out = dict(args)
                # Ring Keypad v2 Entry Control PIN can appear as args.eventData.
                if "eventData" in args_out:
                    args_out["eventData"] = "***"
                out["args"] = args_out
            return out
        except Exception:
            return {"event": "unserializable"}

    def _attach_event_bridges(self, *, client) -> None:
        """
        Wire raw node events to registered listeners.

        In the zwave-js-server-python library version we use, node-originated events are emitted
        by `Node` instances (Controller forwards node events directly to Node and does not emit).
        """

        driver = getattr(client, "driver", None)
        if driver is None:
            return
        controller = getattr(driver, "controller", None)
        if controller is None:
            return

        def _handler(event_name: str, event_data: Any) -> None:
            """Convert and forward a zwave-js event into the listener dispatch pipeline."""
            msg = self._coerce_event_message(event_data)
            if msg is None:
                return
            self._logger.debug("zwavejs event_in %s %s", event_name, self._sanitize_event_for_log(msg))
            # Node event callbacks are invoked on the asyncio event loop thread; run listeners on a
            # plain worker thread so sync Django ORM usage is safe.
            try:
                self._event_executor.submit(self._emit_event, msg)
            except Exception:
                return

        def _attach_node(node) -> None:
            """Attach event listeners to a node once, tracking attached node IDs."""
            try:
                node_id = getattr(node, "node_id", None)
                if node_id is None:
                    node_id = getattr(node, "id", None)
                node_id_int = int(node_id)
            except Exception:
                return

            with self._lock:
                if node_id_int in self._attached_node_ids:
                    return
                self._attached_node_ids.add(node_id_int)

            on = getattr(node, "on", None)
            if not callable(on):
                return
            for event_name in ("notification", "value notification", "value updated", "value added", "value removed"):
                try:
                    on(event_name, lambda data, _name=event_name: _handler(_name, data))
                except Exception:
                    continue

        nodes = getattr(controller, "nodes", None)
        if isinstance(nodes, dict):
            for node in nodes.values():
                _attach_node(node)

        controller_on = getattr(controller, "on", None)
        if callable(controller_on):
            # If nodes are added at runtime, attach listeners for them too.
            def _on_node_added(_data=None) -> None:
                """Attach listeners for any nodes not yet attached."""
                nodes_obj = getattr(controller, "nodes", None)
                if not isinstance(nodes_obj, dict):
                    return
                for node in nodes_obj.values():
                    _attach_node(node)

            try:
                controller_on("node added", _on_node_added)
            except Exception:
                pass

    def get_status(self) -> ZwavejsConnectionStatus:
        """Return the current connection status snapshot."""
        with self._lock:
            settings_obj = dict(self._settings)
            return ZwavejsConnectionStatus(
                configured=_is_configured(settings_obj),
                enabled=bool(settings_obj.get("enabled")),
                connected=self._connected and self._driver_ready,
                home_id=self._home_id,
                last_connect_at=self._last_connect_at,
                last_disconnect_at=self._last_disconnect_at,
                last_error=self._last_error,
            )

    def apply_settings(self, *, settings_obj: ZwavejsConnectionSettings) -> None:
        """Apply runtime settings and start/stop the background connection thread as needed."""
        with self._lock:
            if dict(self._settings) == dict(settings_obj):
                return
            self._settings = dict(settings_obj)
            # api_token is currently unused (zwave-js-server typically runs without auth).

        if not settings_obj.get("enabled"):
            self._disconnect()
            return
        if not _is_configured(settings_obj):
            self._set_error("Z-Wave JS is enabled but ws_url is not configured.")
            self._disconnect()
            return
        if _is_testing_disabled():
            self._set_error("Z-Wave JS integration is disabled during tests.")
            self._disconnect()
            return

        self._ensure_thread_running()

    def ensure_connected(self, *, timeout_seconds: float = 5.0) -> None:
        """Wait for the driver to become ready, raising `ZwavejsNotReachable` on timeout."""
        deadline = time.time() + float(timeout_seconds)
        while time.time() < deadline:
            status = self.get_status()
            if status.connected:
                return
            time.sleep(0.05)
        status = self.get_status()
        raise ZwavejsNotReachable(
            "Timed out waiting for Z-Wave JS driver ready." + (f" last_error={status.last_error}" if status.last_error else "")
        )

    def get_home_id(self) -> int | None:
        """Return the active home id if known, else `None`."""
        with self._lock:
            return self._home_id

    def test_connection(self, *, settings_obj: ZwavejsConnectionSettings, timeout_seconds: float | None = None) -> None:
        """Attempt a short-lived connect/listen handshake to validate settings."""
        if _is_testing_disabled():
            raise ZwavejsNotReachable("Z-Wave JS integration is disabled during tests.")
        if not _is_configured(settings_obj):
            raise ZwavejsNotConfigured("Z-Wave JS ws_url is required and must start with ws:// or wss://.")

        imported = _import_zwavejs_client()
        if imported is None:
            raise ZwavejsClientUnavailable("Z-Wave JS client library not installed (missing `zwave-js-server-python`).")
        aiohttp, Client, _ = imported

        ws_url = (settings_obj.get("ws_url") or "").strip()
        _validate_ws_url(ws_url)
        timeout = float(timeout_seconds or settings_obj.get("connect_timeout_seconds") or 5)

        async def _run():
            """Connect, start listening, and wait for driver readiness before disconnecting."""
            async with aiohttp.ClientSession() as session:
                client = Client(ws_url, session)
                await asyncio.wait_for(client.connect(), timeout=timeout)
                driver_ready = asyncio.Event()
                listen_task = asyncio.create_task(client.listen(driver_ready))
                try:
                    await asyncio.wait_for(driver_ready.wait(), timeout=timeout)
                finally:
                    await client.disconnect()
                    with contextlib.suppress(Exception):
                        await listen_task

        try:
            asyncio.run(_run())
        except Exception as exc:
            raise ZwavejsNotReachable(str(exc)) from exc

    def controller_get_state(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        """Return a controller state snapshot (nodes + controller metadata)."""
        return self._run_coro(self._async_controller_get_state(), timeout_seconds=timeout_seconds)

    def node_get_defined_value_ids(self, *, node_id: int, timeout_seconds: float = 5.0) -> list[dict[str, Any]]:
        """Return the node's defined value IDs as dicts suitable for API transport."""
        return self._run_coro(self._async_node_get_defined_value_ids(node_id=node_id), timeout_seconds=timeout_seconds)

    def node_get_value_metadata(self, *, node_id: int, value_id: dict[str, Any], timeout_seconds: float = 5.0) -> dict[str, Any]:
        """Return metadata for the given value id on a node."""
        return self._run_coro(
            self._async_node_get_value_metadata(node_id=node_id, value_id=value_id),
            timeout_seconds=timeout_seconds,
        )

    def node_get_value(self, *, node_id: int, value_id: dict[str, Any], timeout_seconds: float = 5.0) -> object:
        """Return the current cached value for a node value id (no network I/O expected)."""
        # Cached read; no I/O expected.
        return self._run_coro(self._async_node_get_value(node_id=node_id, value_id=value_id), timeout_seconds=timeout_seconds)

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
        """Write a node value by value id components, waiting for a result (best-effort)."""
        if not isinstance(node_id, int) or node_id <= 0:
            raise ZwavejsCommandValidationError("node_id must be a positive integer.")
        if not isinstance(endpoint, int) or endpoint < 0:
            raise ZwavejsCommandValidationError("endpoint must be an integer >= 0.")
        if not isinstance(command_class, int) or command_class <= 0:
            raise ZwavejsCommandValidationError("command_class must be a positive integer.")
        if not isinstance(property, (str, int)):
            raise ZwavejsCommandValidationError("property must be a string or number.")
        if isinstance(property, str) and not property.strip():
            raise ZwavejsCommandValidationError("property must be a non-empty string.")

        value_id: dict[str, Any] = {"endpoint": endpoint, "commandClass": command_class, "property": property}
        if property_key is not None:
            value_id["propertyKey"] = property_key
        self._logger.debug(
            "zwavejs event_out set_value node_id=%s value_id=%s value=%s",
            node_id,
            value_id,
            value if isinstance(value, (int, float, str, bool, type(None))) else type(value).__name__,
        )
        self._run_coro(self._async_set_value(node_id=node_id, value_id=value_id, value=value), timeout_seconds=10.0)

    # ---- internals ----
    def _set_error(self, error: str | None) -> None:
        """Set the manager's last error message (best-effort, no raising)."""
        with self._lock:
            self._last_error = error

    def _ensure_thread_running(self) -> None:
        """Start the background asyncio thread if dependencies are available."""
        imported = _import_zwavejs_client()
        if imported is None:
            self._set_error("Z-Wave JS client library not installed (missing `zwave-js-server-python`).")
            self._disconnect()
            return

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            thread = threading.Thread(target=self._thread_main, name="zwavejs-connection", daemon=True)
            self._thread = thread
        thread.start()

    def _disconnect(self) -> None:
        """Stop the background thread/event loop and reset connection state (idempotent)."""
        self._stop_event.set()
        loop = None
        thread = None
        with self._lock:
            loop = self._loop
            thread = self._thread
            self._connected = False
            self._driver_ready = False
            self._home_id = None
            self._driver_ready_event.clear()
            self._attached_node_ids.clear()

        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)
        with self._lock:
            self._thread = None
            self._loop = None
            self._client = None
            self._aiohttp_session = None
            self._last_disconnect_at = _now()
        self._stop_event.clear()

    def _thread_main(self) -> None:
        """Background thread entrypoint running an asyncio event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        try:
            loop.run_until_complete(self._async_run_loop())
        except RuntimeError as exc:
            # `loop.stop()` during shutdown can stop the loop before `_async_run_loop()` returns.
            if "Event loop stopped before Future completed" not in str(exc):
                raise
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    async def _async_run_loop(self) -> None:
        """Async connection loop that reconnects with backoff until stopped or disabled."""
        imported = _import_zwavejs_client()
        if imported is None:
            return
        aiohttp, Client, _ = imported

        attempt = 0
        while not self._stop_event.is_set():
            with self._lock:
                settings_obj = dict(self._settings)

            if not settings_obj.get("enabled"):
                return

            ws_url = (settings_obj.get("ws_url") or "").strip()
            if not ws_url:
                self._set_error("Z-Wave JS ws_url is not configured.")
                return
            try:
                _validate_ws_url(ws_url)
            except ZwavejsNotConfigured as exc:
                self._set_error(str(exc))
                return

            reconnect_min = int(settings_obj.get("reconnect_min_seconds") or 1)
            reconnect_max = int(settings_obj.get("reconnect_max_seconds") or 30)
            timeout = float(settings_obj.get("connect_timeout_seconds") or 10)
            settings_fingerprint = (ws_url, bool(settings_obj.get("enabled")))

            try:
                async with aiohttp.ClientSession() as session:
                    client = Client(ws_url, session)
                    with self._lock:
                        self._aiohttp_session = session
                        self._client = client
                        self._connected = False
                        self._driver_ready = False
                        self._home_id = None
                        self._driver_ready_event.clear()
                        self._attached_node_ids.clear()

                    await asyncio.wait_for(client.connect(), timeout=timeout)
                    with self._lock:
                        self._connected = True
                        self._last_connect_at = _now()
                        try:
                            self._home_id = int(getattr(client.version, "home_id", None)) if client.version else None
                        except Exception:
                            self._home_id = None
                        self._last_error = None

                    driver_ready = asyncio.Event()
                    listen_task = asyncio.create_task(client.listen(driver_ready))

                    # Wait for driver_ready or early exit.
                    while not self._stop_event.is_set():
                        if listen_task.done():
                            break
                        if driver_ready.is_set():
                            with self._lock:
                                self._driver_ready = True
                            self._driver_ready_event.set()
                            try:
                                self._attach_event_bridges(client=client)
                            except Exception:
                                pass
                            break
                        await asyncio.sleep(0.05)

                    # Main connected loop: keep listening until stop or settings change.
                    while not self._stop_event.is_set() and not listen_task.done():
                        with self._lock:
                            current = dict(self._settings)
                        if (current.get("ws_url") or "").strip() != settings_fingerprint[0] or bool(current.get("enabled")) != settings_fingerprint[1]:
                            break
                        await asyncio.sleep(0.2)

                    await client.disconnect()
                    with contextlib.suppress(Exception):
                        await listen_task
            except Exception as exc:
                self._set_error(str(exc))
            finally:
                with self._lock:
                    self._connected = False
                    self._driver_ready = False
                    self._driver_ready_event.clear()
                    self._client = None
                    self._aiohttp_session = None
                    self._last_disconnect_at = _now()

            if self._stop_event.is_set():
                return

            attempt += 1
            await asyncio.sleep(_backoff_seconds(attempt=attempt, min_seconds=reconnect_min, max_seconds=reconnect_max))

    def _run_coro(self, coro, *, timeout_seconds: float):
        """Run an async coroutine on the background loop and return its result or raise on failure."""
        loop = None
        with self._lock:
            loop = self._loop
        if loop is None:
            raise ZwavejsNotConnected("Not connected to Z-Wave JS server.")
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            return fut.result(timeout=timeout_seconds)
        except Exception as exc:
            raise ZwavejsCommandError(str(exc)) from exc

    async def _async_get_node(self, *, node_id: int):
        """Resolve and return the zwave-js node object or raise if missing/unavailable."""
        imported = _import_zwavejs_client()
        if imported is None:
            raise ZwavejsClientUnavailable("Z-Wave JS client library not installed (missing `zwave-js-server-python`).")
        with self._lock:
            client = self._client
        if client is None or not getattr(client, "connected", False) or not getattr(client, "driver", None):
            raise ZwavejsNotConnected("Not connected to Z-Wave JS server.")
        driver = client.driver
        node = driver.controller.nodes.get(int(node_id))
        if node is None:
            raise ZwavejsCommandError(f"Node {node_id} not found.")
        return node

    async def _async_controller_get_state(self) -> dict[str, Any]:
        """Return the current controller state as a JSON-friendly dict."""
        with self._lock:
            client = self._client
        if client is None or not getattr(client, "connected", False) or not getattr(client, "driver", None):
            raise ZwavejsNotConnected("Not connected to Z-Wave JS server.")
        controller = client.driver.controller
        nodes = [dict(node.data) for node in controller.nodes.values()]
        controller_data = dict(getattr(controller, "data", {}) or {})
        return {"state": {"nodes": nodes, "controller": controller_data}}

    async def _async_node_get_defined_value_ids(self, *, node_id: int) -> list[dict[str, Any]]:
        """Return a list of defined value ids for a node, normalized to dicts."""
        node = await self._async_get_node(node_id=int(node_id))
        values = await node.async_get_defined_value_ids()
        out: list[dict[str, Any]] = []
        for value in values:
            try:
                out.append(_value_id_dict_from_value_data(dict(value.data)))
            except Exception:
                continue
        return out

    async def _async_node_get_value_metadata(self, *, node_id: int, value_id: dict[str, Any]) -> dict[str, Any]:
        """Fetch value metadata for a node value id."""
        imported = _import_zwavejs_client()
        if imported is None:
            raise ZwavejsClientUnavailable("Z-Wave JS client library not installed (missing `zwave-js-server-python`).")
        _, _, _get_value_id_str_from_dict = imported

        node = await self._async_get_node(node_id=int(node_id))
        value_id_str = _get_value_id_str_from_dict(node, value_id)
        meta = await node.async_get_value_metadata(value_id_str)
        return dict(getattr(meta, "data", {}) or {})

    async def _async_node_get_value(self, *, node_id: int, value_id: dict[str, Any]) -> object:
        """Return the current cached value for a node value id."""
        imported = _import_zwavejs_client()
        if imported is None:
            raise ZwavejsClientUnavailable("Z-Wave JS client library not installed (missing `zwave-js-server-python`).")
        _, _, _get_value_id_str_from_dict = imported

        node = await self._async_get_node(node_id=int(node_id))
        value_id_str = _get_value_id_str_from_dict(node, value_id)
        value_obj = node.values.get(value_id_str)
        return getattr(value_obj, "value", None) if value_obj is not None else None

    async def _async_set_value(self, *, node_id: int, value_id: dict[str, Any], value: object) -> None:
        """Set a node value and wait for the result."""
        imported = _import_zwavejs_client()
        if imported is None:
            raise ZwavejsClientUnavailable("Z-Wave JS client library not installed (missing `zwave-js-server-python`).")
        _, _, _get_value_id_str_from_dict = imported

        node = await self._async_get_node(node_id=int(node_id))
        value_id_str = _get_value_id_str_from_dict(node, value_id)
        await node.async_set_value(value_id_str, value, wait_for_result=True)


def build_zwavejs_entity_id(*, home_id: int, node_id: int, value_id: dict[str, Any]) -> str:
    """Build a stable, namespaced entity id string for a Z-Wave JS value id."""
    command_class = value_id.get("commandClass")
    endpoint = value_id.get("endpoint", 0)
    prop = value_id.get("property")
    prop_key = value_id.get("propertyKey", "-")
    return f"zwavejs:{home_id}:{node_id}:{endpoint}:{command_class}:{prop}:{prop_key}"


def normalize_entity_state(*, value: object) -> str | None:
    """Normalize value types into simple string states used by the entity registry."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return None
    return str(value)


def infer_entity_domain(*, value: object) -> str:
    """Infer a Home Assistant-like entity domain from a raw value type."""
    if isinstance(value, bool):
        return "binary_sensor"
    if isinstance(value, (int, float)):
        return "sensor"
    return "sensor"


zwavejs_connection_manager = ZwavejsConnectionManager()
