from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, TypedDict

from config.domain_exceptions import GatewayError, GatewayValidationError

GATEWAY_NAME = "MQTT"

_CONNACK_RC_REASON: dict[int, str] = {
    # MQTT 3.1.1 CONNACK return codes
    0: "Connection accepted",
    1: "Unacceptable protocol version",
    2: "Identifier rejected",
    3: "Server unavailable",
    4: "Bad username or password",
    5: "Not authorized",
}


def _format_connect_error(*, rc_int: int, settings: "MqttConnectionSettings | None" = None) -> str:
    reason = _CONNACK_RC_REASON.get(rc_int, "Unknown error")
    message = f"MQTT connect failed: {reason} (rc={rc_int})."

    if not settings:
        return message

    username = (settings.get("username") or "").strip()
    password = (settings.get("password") or "").strip()

    if rc_int in {4, 5}:
        if not username and not password:
            return f"{message} Broker likely requires authentication; provide a username/password."
        return f"{message} Check username/password and broker ACLs."
    if rc_int == 2:
        client_id = (settings.get("client_id") or "").strip()
        if client_id:
            return f"{message} Try a different client_id."
        return f"{message} Set a unique client_id."
    if rc_int == 3:
        return f"{message} Verify host/port and broker availability."

    return message


class MqttGatewayError(GatewayError):
    gateway_name = GATEWAY_NAME


class MqttValidationError(GatewayValidationError):
    gateway_name = GATEWAY_NAME


class MqttNotConfigured(MqttGatewayError):
    pass


class MqttNotReachable(MqttGatewayError):
    def __init__(self, error: str | None = None):
        """Wrap an optional low-level reachability error string."""
        self.error = error
        super().__init__(error or "MQTT broker is not reachable.")


class MqttClientUnavailable(MqttGatewayError):
    pass


class MqttPublishError(MqttGatewayError):
    def __init__(self, topic: str, error: str | None = None):
        self.operation = f"publish to {topic}"
        self.error = error
        message = f"{GATEWAY_NAME} publish to {topic} failed."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)


class MqttSubscribeError(MqttGatewayError):
    def __init__(self, topic: str, error: str | None = None):
        self.operation = f"subscribe to {topic}"
        self.error = error
        message = f"{GATEWAY_NAME} subscribe to {topic} failed."
        if error:
            message = f"{message} Error: {error}"
        super().__init__(message)


class MqttConnectionSettings(TypedDict, total=False):
    enabled: bool
    host: str
    port: int
    username: str
    password: str
    use_tls: bool
    tls_insecure: bool
    client_id: str
    keepalive_seconds: int
    connect_timeout_seconds: float


@dataclass(frozen=True)
class MqttConnectionStatus:
    configured: bool
    enabled: bool
    connected: bool
    last_connect_at: datetime | None = None
    last_disconnect_at: datetime | None = None
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize status to a JSON-friendly dict for API responses."""
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "connected": self.connected,
            "last_connect_at": self.last_connect_at.isoformat() if self.last_connect_at else None,
            "last_disconnect_at": self.last_disconnect_at.isoformat() if self.last_disconnect_at else None,
            "last_error": self.last_error,
        }


def _now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def _is_configured(settings: MqttConnectionSettings) -> bool:
    """Return True if required broker settings are present."""
    return bool(settings.get("host")) and bool(settings.get("port"))


class MqttConnectionManager:
    """
    Minimal MQTT connection manager (v1).

    - Keeps a best-effort long-lived connection when enabled.
    - Provides a separate `test_connection` for onboarding validation.
    - Avoids hard dependency on `paho-mqtt` at import time; reports a clear status error if missing.
    """

    def __init__(self) -> None:
        """Initialize manager state (no network I/O)."""
        self._lock = threading.Lock()
        self._client = None
        self._settings: MqttConnectionSettings = {}
        self._connected = False
        self._last_connect_at: datetime | None = None
        self._last_disconnect_at: datetime | None = None
        self._last_error: str | None = None
        # Subscription map keyed by topic filter. Each filter can have multiple callbacks.
        # The broker subscription is applied once per filter with the max requested QoS.
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._on_connect_hooks: list[callable] = []
        self._logger = logging.getLogger(__name__)

    @staticmethod
    def _topic_matches(*, topic_filter: str, topic: str) -> bool:
        """
        Return True if an MQTT topic matches a subscription filter.

        Supports the standard `+` and `#` wildcards.
        """
        if topic_filter == topic:
            return True
        if "+" not in topic_filter and "#" not in topic_filter:
            return False

        filt_parts = [p for p in str(topic_filter).split("/") if p != ""]
        topic_parts = [p for p in str(topic).split("/") if p != ""]

        i = 0
        while i < len(filt_parts):
            fp = filt_parts[i]
            if fp == "#":
                return True
            if i >= len(topic_parts):
                return False
            tp = topic_parts[i]
            if fp != "+" and fp != tp:
                return False
            i += 1
        return i == len(topic_parts)

    def get_status(self) -> MqttConnectionStatus:
        """Return the current broker settings and connection status snapshot."""
        with self._lock:
            settings = dict(self._settings)
            return MqttConnectionStatus(
                configured=_is_configured(settings),
                enabled=bool(settings.get("enabled")),
                connected=self._connected,
                last_connect_at=self._last_connect_at,
                last_disconnect_at=self._last_disconnect_at,
                last_error=self._last_error,
            )

    def apply_settings(self, *, settings: MqttConnectionSettings) -> None:
        """Apply runtime connection settings and connect/disconnect accordingly."""
        with self._lock:
            same_settings = dict(self._settings) == dict(settings)
            self._settings = dict(settings)

        if not settings.get("enabled"):
            self._disconnect()
            return
        if not _is_configured(settings):
            self._set_error("MQTT is enabled but host/port are not configured.")
            self._disconnect()
            return
        # If settings are unchanged and we're already connected, avoid reconnect churn.
        # If settings are unchanged but we're disconnected, we still retry connecting.
        if same_settings and self.get_status().connected:
            return
        self._connect(settings=settings)

    def test_connection(self, *, settings: MqttConnectionSettings, timeout_seconds: float | None = None) -> None:
        """Attempt a short-lived connection to validate broker settings."""
        if not _is_configured(settings):
            raise MqttValidationError("MQTT host and port are required.")

        mqtt = self._import_paho()
        if mqtt is None:
            raise MqttClientUnavailable("MQTT client library not installed (missing `paho-mqtt`).")

        timeout = float(timeout_seconds or settings.get("connect_timeout_seconds") or 5)
        connected_evt = threading.Event()
        result: dict[str, Any] = {"rc": None, "error": None}

        client = self._build_client(mqtt=mqtt, settings=settings)

        def on_connect(_client, _userdata, _flags, rc, _properties=None):
            """Capture connect return code and release the waiter."""
            result["rc"] = rc
            connected_evt.set()

        def on_disconnect(_client, _userdata, rc, _properties=None):
            """Ignore disconnects during `test_connection` teardown."""
            # ignore for test
            pass

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect

        try:
            client.connect_async(settings.get("host", ""), int(settings.get("port", 1883)), int(settings.get("keepalive_seconds", 30)))
            client.loop_start()
            if not connected_evt.wait(timeout=timeout):
                raise MqttNotReachable("Timed out connecting to MQTT broker.")
            rc = result["rc"]
            try:
                rc_int = int(getattr(rc, "value", rc))
            except Exception:
                rc_int = 1
            if rc_int != 0:
                raise MqttNotReachable(_format_connect_error(rc_int=rc_int, settings=settings))
        finally:
            try:
                client.disconnect()
            except Exception:
                self._logger.debug("Cleanup failed during disconnect", exc_info=True)
            try:
                client.loop_stop()
            except Exception:
                self._logger.debug("Cleanup failed during disconnect", exc_info=True)

    def _set_error(self, error: str | None) -> None:
        """Set the manager's last error message (best-effort, no raising)."""
        with self._lock:
            self._last_error = error

    def _disconnect(self) -> None:
        """Disconnect and tear down the current client (idempotent)."""
        with self._lock:
            client = self._client
            self._client = None
            was_connected = self._connected
            self._connected = False
            self._last_disconnect_at = _now() if was_connected else self._last_disconnect_at

        if client is None:
            return
        try:
            client.disconnect()
        except Exception:
            self._logger.debug("Cleanup failed during disconnect", exc_info=True)
        try:
            client.loop_stop()
        except Exception:
            self._logger.debug("Cleanup failed during disconnect", exc_info=True)

    def _connect(self, *, settings: MqttConnectionSettings) -> None:
        """Start (or restart) an async MQTT connection using the provided settings."""
        mqtt = self._import_paho()
        if mqtt is None:
            self._set_error("MQTT client library not installed (missing `paho-mqtt`).")
            self._disconnect()
            return

        client = self._build_client(mqtt=mqtt, settings=settings)

        def on_connect(_client, _userdata, _flags, rc, _properties=None):
            """Update state on successful connect and re-apply subscriptions."""
            try:
                rc_int = int(getattr(rc, "value", rc))
            except Exception:
                rc_int = 1
            if rc_int == 0:
                with self._lock:
                    self._connected = True
                    self._last_connect_at = _now()
                    self._last_error = None
                self._resubscribe()
                self._run_on_connect_hooks()
            else:
                with self._lock:
                    self._connected = False
                    self._last_error = _format_connect_error(rc_int=rc_int, settings=settings)

        def on_disconnect(_client, _userdata, rc, _properties=None):
            """Update state on disconnect, capturing unexpected disconnects as errors."""
            with self._lock:
                self._connected = False
                self._last_disconnect_at = _now()
                try:
                    rc_int = int(getattr(rc, "value", rc))
                except Exception:
                    rc_int = 1
                if rc_int != 0:
                    self._last_error = f"MQTT disconnected (rc={rc_int})."

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = self._on_message

        # Replace any existing client
        self._disconnect()
        with self._lock:
            self._client = client

        try:
            client.connect_async(
                settings.get("host", ""),
                int(settings.get("port", 1883)),
                int(settings.get("keepalive_seconds", 30)),
            )
            client.loop_start()
        except Exception as exc:
            self._set_error(str(exc))
            self._disconnect()

    @staticmethod
    def _import_paho():
        """Import `paho.mqtt.client` if installed; return None if unavailable."""
        try:
            import paho.mqtt.client as mqtt  # type: ignore[import-not-found]

            return mqtt
        except Exception:
            return None

    @staticmethod
    def _build_client(*, mqtt, settings: MqttConnectionSettings):
        """Create and configure a paho client from settings (auth/TLS/client_id)."""
        client_id = str(settings.get("client_id") or "latchpoint-alarm")
        try:
            client = mqtt.Client(client_id=client_id)
        except TypeError:
            client = mqtt.Client()

        username = settings.get("username") or ""
        password = settings.get("password") or ""
        if username or password:
            client.username_pw_set(username, password)

        if settings.get("use_tls"):
            client.tls_set()
            if settings.get("tls_insecure"):
                client.tls_insecure_set(True)

        return client

    def publish(self, *, topic: str, payload: str, qos: int = 0, retain: bool = False) -> None:
        """Publish a string payload to a topic, raising if the manager is not connected."""
        with self._lock:
            client = self._client
            connected = self._connected
        if client is None or not connected:
            raise MqttNotReachable("MQTT is not connected.")
        try:
            client.publish(topic, payload=payload, qos=qos, retain=retain)
        except Exception as exc:
            raise MqttPublishError(topic, str(exc)) from exc

    def subscribe(self, *, topic: str, qos: int = 0, callback) -> None:
        """
        Register a subscription callback.

        The subscription will be (re)applied on every connect.
        """
        with self._lock:
            entry = self._subscriptions.get(topic)
            if not entry:
                entry = {"qos": int(qos), "callbacks": []}
                self._subscriptions[topic] = entry
            entry["qos"] = max(int(entry.get("qos") or 0), int(qos))
            callbacks = entry.get("callbacks")
            if not isinstance(callbacks, list):
                callbacks = []
                entry["callbacks"] = callbacks
            if callback not in callbacks:
                callbacks.append(callback)
            client = self._client
            connected = self._connected
        if client is not None and connected:
            try:
                client.subscribe(topic, qos=qos)
            except Exception as exc:
                raise MqttSubscribeError(topic, str(exc)) from exc

    def unsubscribe(self, *, topic: str, callback=None) -> None:
        """
        Unregister a subscription callback (or all callbacks) for a topic filter.

        Best-effort: broker unsubscribe is attempted only when no callbacks remain.
        """
        with self._lock:
            entry = self._subscriptions.get(topic)
            if not entry:
                return
            callbacks = entry.get("callbacks")
            if not isinstance(callbacks, list):
                callbacks = []
                entry["callbacks"] = callbacks
            if callback is None:
                callbacks.clear()
            else:
                try:
                    callbacks.remove(callback)
                except ValueError:
                    pass

            should_unsubscribe = not callbacks
            if should_unsubscribe:
                self._subscriptions.pop(topic, None)
            client = self._client
            connected = self._connected

        if should_unsubscribe and client is not None and connected:
            try:
                client.unsubscribe(topic)
            except Exception:
                self._logger.debug("Unsubscribe failed for %s", topic, exc_info=True)

    def register_on_connect(self, callback) -> None:
        """Register a callback to run on successful connect (best-effort)."""
        with self._lock:
            self._on_connect_hooks.append(callback)

    def _resubscribe(self) -> None:
        """Re-apply topic subscriptions on (re)connect."""
        with self._lock:
            client = self._client
            subs = dict(self._subscriptions)
        if client is None:
            return
        for topic, entry in subs.items():
            qos = int(entry.get("qos") or 0)
            try:
                client.subscribe(topic, qos=qos)
            except Exception as exc:
                self._logger.warning("MQTT subscribe failed for %s: %s", topic, exc)

    def _run_on_connect_hooks(self) -> None:
        """Run registered connect hooks on a background thread."""
        with self._lock:
            hooks = list(self._on_connect_hooks)

        def _run():
            """Invoke each hook in order, swallowing errors."""
            for hook in hooks:
                try:
                    hook()
                except Exception as exc:
                    self._logger.warning("MQTT on_connect hook failed: %s", exc)

        threading.Thread(target=_run, daemon=True).start()

    def _on_message(self, _client, _userdata, msg) -> None:
        """Dispatch incoming messages to the registered per-topic callback (if any)."""
        topic = getattr(msg, "topic", "")
        payload_bytes = getattr(msg, "payload", b"")
        try:
            payload = payload_bytes.decode("utf-8", errors="replace")
        except Exception:
            payload = str(payload_bytes)

        callbacks: list[callable] = []
        with self._lock:
            subs = dict(self._subscriptions)
        for topic_filter, entry in subs.items():
            try:
                if not self._topic_matches(topic_filter=topic_filter, topic=topic):
                    continue
            except Exception:
                self._logger.debug("Topic match failed for %s", topic_filter, exc_info=True)
                continue
            cbs = entry.get("callbacks") if isinstance(entry, dict) else None
            if isinstance(cbs, list):
                callbacks.extend([cb for cb in cbs if callable(cb)])
        if not callbacks:
            return
        for callback in callbacks:
            try:
                callback(topic=topic, payload=payload)
            except Exception as exc:
                self._logger.warning("MQTT message handler failed for %s: %s", topic, exc)


mqtt_connection_manager = MqttConnectionManager()
