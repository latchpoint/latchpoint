from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger("integrations_home_assistant")

_CACHE_LEADER_KEY = "integrations_home_assistant:state_stream:leader"
_LEADER_TTL_SECONDS = 60
_LEADER_HEARTBEAT_SECONDS = 20
_RECONNECT_BACKOFF_INITIAL_SECONDS = 1.0
_RECONNECT_BACKOFF_MAX_SECONDS = 30.0
# An authed session has to stay up this long before its drop resets the backoff (#114).
_RECONNECT_HEALTHY_SESSION_SECONDS = 30.0
# How long `restart()` waits for the old thread before starting the new one anyway. Kept short because
# it runs in the settings PATCH request, and a stopped thread can't keep a session open (see `restart`).
_RESTART_JOIN_TIMEOUT_SECONDS = 1.0

# The stream reads the clock through this hook so tests can swap it without patching `time` process-wide.
_monotonic = time.monotonic


def _build_ws_url(base_url: str) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    if base_url.startswith("https://"):
        return f"wss://{base_url[len('https://') :]}/api/websocket"
    if base_url.startswith("http://"):
        return f"ws://{base_url[len('http://') :]}/api/websocket"
    # Fallback: assume http and let HA/infra redirect if needed (best-effort).
    return f"ws://{base_url}/api/websocket"


def _parse_ha_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    # HA often uses Zulu time (e.g., "2026-01-10T12:34:56.123Z") which
    # `datetime.fromisoformat` doesn't accept on older Python versions.
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt


@dataclass(frozen=True)
class _RuntimeSettings:
    enabled: bool
    base_url: str
    token: str


def _get_runtime_settings() -> _RuntimeSettings:
    from integrations_home_assistant.connection import get_cached_connection, warm_up_cached_connection_if_needed

    warm_up_cached_connection_if_needed()
    cached = get_cached_connection()
    if cached is None:
        return _RuntimeSettings(enabled=False, base_url="", token="")
    if not cached.enabled:
        return _RuntimeSettings(enabled=False, base_url="", token="")
    base_url = (cached.base_url or "").strip()
    token = (cached.token or "").strip()
    if not base_url or not token:
        return _RuntimeSettings(enabled=False, base_url=base_url, token="")
    return _RuntimeSettings(enabled=True, base_url=base_url, token=token)


class HomeAssistantStateStream:
    """
    Persistent Home Assistant `/api/websocket` state_changed subscription.

    Emits entity changes into the ADR 0057 dispatcher after updating `Entity.last_state`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._leader_id = uuid4().hex
        self._ws_app: Any | None = None
        self._settings: _RuntimeSettings = _RuntimeSettings(enabled=False, base_url="", token="")
        self._next_subscribe_id = 1

    def apply_runtime_settings_from_active_profile(self) -> None:
        """Start/stop the stream based on the current cached HA connection settings."""
        with self._lock:
            # Read under the lock too, so two applies at once can't store the older settings last (#132).
            settings = _get_runtime_settings()
            changed = settings != self._settings
            self._settings = settings
        if not settings.enabled:
            self.stop()
            return
        if changed:
            self.restart()
            return
        self.start()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive() and not self._stop.is_set():
                return
            # Each thread gets its own stop event. A thread still on its way out after `stop()` keeps its
            # event set, so starting a new one here can't revive it.
            stop = threading.Event()
            self._stop = stop
            self._thread = threading.Thread(target=self._run, args=(stop,), name="ha-state-stream", daemon=True)
            self._thread.start()

    def stop(self) -> threading.Thread | None:
        """Signal the current thread to stop and close its websocket. Returns the thread without joining it."""
        with self._lock:
            self._stop.set()
            thread = self._thread
            ws = self._ws_app
        try:
            if ws is not None:
                ws.close()
        except Exception:
            logger.debug("WebSocket close failed", exc_info=True)
        return thread

    def restart(self) -> None:
        """
        Stop the current thread and start a new one that picks up the latest settings.

        The join is bounded. If the old thread hasn't exited in time (stuck in a blocking connect, or a
        live session that takes a few seconds to notice the close), the new thread starts anyway. The old
        thread keeps its own stop event set, so it exits as soon as it unblocks, and any session it opens
        in the meantime is closed before it authenticates (see `_connect_and_listen`).
        """
        old_thread = self.stop()
        if old_thread is not None and old_thread is not threading.current_thread():
            old_thread.join(timeout=_RESTART_JOIN_TIMEOUT_SECONDS)
            if old_thread.is_alive():
                logger.info("HA state stream: previous thread still exiting, starting the new one anyway")
        self.start()

    def _is_leader(self) -> bool:
        """
        Best-effort leader lock to avoid multiple HA connections in multi-worker deployments.

        Note: this only works when Django cache is shared between workers.
        """
        try:
            # Acquire leadership if free.
            if cache.add(_CACHE_LEADER_KEY, self._leader_id, timeout=_LEADER_TTL_SECONDS):
                return True
            current = cache.get(_CACHE_LEADER_KEY)
            if current == self._leader_id:
                # Refresh TTL.
                cache.set(_CACHE_LEADER_KEY, self._leader_id, timeout=_LEADER_TTL_SECONDS)
                return True
            return False
        except Exception:
            # No cache / cache error: fall back to per-process behavior.
            return True

    def _run(self, stop: threading.Event) -> None:
        # `stop` is this thread's own event from `start()`. Never use `self._stop` here, after a restart
        # that's the new thread's event.
        backoff_seconds = _RECONNECT_BACKOFF_INITIAL_SECONDS
        last_leader_refresh = 0.0

        while not stop.is_set():
            with self._lock:
                settings = self._settings

            if not settings.enabled:
                return

            # Leadership gating.
            now_monotonic = _monotonic()
            if now_monotonic - last_leader_refresh >= _LEADER_HEARTBEAT_SECONDS:
                last_leader_refresh = now_monotonic
            if not self._is_leader():
                if stop.wait(1.0):
                    return
                continue

            ws_url = _build_ws_url(settings.base_url)
            try:
                authed_at = self._connect_and_listen(ws_url=ws_url, token=settings.token, stop=stop)
            except Exception as exc:
                logger.warning("HA state stream disconnected: %s", exc)
                authed_at = None

            # `run_forever` returns (rather than raises) on a refused connection, so back off after
            # every attempt. Only a session that stayed up for a while after auth_ok resets the delay,
            # so HA (or a proxy) dropping the connection right after auth keeps backing off.
            # The threshold never goes below the backoff cap (#119). A session that resets the delay
            # reconnects 1s after it drops, so with a lower threshold something that cuts the connection
            # right after it would reconnect faster than the capped failure rate forever (#114 again).
            healthy_after = max(_RECONNECT_HEALTHY_SESSION_SECONDS, _RECONNECT_BACKOFF_MAX_SECONDS)
            healthy = authed_at is not None and _monotonic() - authed_at >= healthy_after
            if healthy:
                backoff_seconds = _RECONNECT_BACKOFF_INITIAL_SECONDS
            if stop.wait(backoff_seconds):
                return
            if not healthy:
                backoff_seconds = min(_RECONNECT_BACKOFF_MAX_SECONDS, backoff_seconds * 2.0)

    def _connect_and_listen(self, *, ws_url: str, token: str, stop: threading.Event) -> float | None:
        """Run one websocket session until it closes; return the `_monotonic()` of `auth_ok`, or None."""
        import websocket

        authed = {"at": None}

        def _on_open(ws) -> None:
            # `stop()` can land after `_ws_app` is set but before `run_forever` starts. Its `close()` is lost
            # then (`run_forever` resets `keep_running` and there's no socket yet), so check again here.
            if stop.is_set():
                ws.close()
                return
            logger.info("HA state stream connected (ws_url=%s)", ws_url)

        def _on_message(ws, message: str) -> None:
            if stop.is_set():
                # A stopped session never authenticates or handles events.
                ws.close()
                return
            try:
                obj = json.loads(message) if message else None
            except Exception:
                return
            if not isinstance(obj, dict):
                return

            msg_type = obj.get("type")
            if msg_type == "auth_required":
                ws.send(json.dumps({"type": "auth", "access_token": token}))
                return

            if msg_type == "auth_ok":
                authed["at"] = _monotonic()
                sub_id = self._next_subscribe_id
                self._next_subscribe_id += 1
                ws.send(
                    json.dumps(
                        {
                            "id": sub_id,
                            "type": "subscribe_events",
                            "event_type": "state_changed",
                        }
                    )
                )
                logger.info("HA state stream subscribed to state_changed")
                return

            if msg_type == "auth_invalid":
                logger.error("HA state stream auth_invalid: %s", obj.get("message") or "unknown")
                ws.close()
                return

            if msg_type != "event":
                return

            event = obj.get("event")
            if not isinstance(event, dict) or event.get("event_type") != "state_changed":
                return

            data = event.get("data")
            if not isinstance(data, dict):
                return

            self._handle_state_changed(event=event, data=data)

        def _on_error(_ws, error) -> None:
            logger.debug("HA state stream error: %s", error)

        def _on_close(_ws, status_code, msg) -> None:
            if authed["at"] is not None:
                logger.info("HA state stream closed (code=%s, msg=%s)", status_code, msg)
            else:
                logger.warning("HA state stream closed before auth (code=%s, msg=%s)", status_code, msg)

        ws_app = websocket.WebSocketApp(
            ws_url,
            on_open=_on_open,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )

        with self._lock:
            # `stop()` sets the event under this lock, so either it sees `_ws_app` and closes it, or we see
            # the event here and don't connect.
            if stop.is_set():
                return None
            self._ws_app = ws_app

        try:
            # run_forever blocks until closed.
            ws_app.run_forever(ping_interval=30, ping_timeout=10)
        finally:
            with self._lock:
                if self._ws_app is ws_app:
                    self._ws_app = None
        return authed["at"]

    def _handle_state_changed(self, *, event: dict[str, Any], data: dict[str, Any]) -> None:
        close_old_connections()

        entity_id = data.get("entity_id")
        if not isinstance(entity_id, str) or not entity_id.strip():
            return
        entity_id = entity_id.strip()

        new_state = data.get("new_state")
        old_state = data.get("old_state")
        new_state_obj = new_state if isinstance(new_state, dict) else {}
        old_state_obj = old_state if isinstance(old_state, dict) else {}

        new_state_str = new_state_obj.get("state")
        old_state_str = old_state_obj.get("state")
        if not isinstance(new_state_str, str):
            new_state_str = None
        if not isinstance(old_state_str, str):
            old_state_str = None

        # Prefer the HA event time for scheduling semantics, fall back to wall-clock.
        changed_at = (
            _parse_ha_datetime(new_state_obj.get("last_changed"))
            or _parse_ha_datetime(event.get("time_fired"))
            or timezone.now()
        )
        seen_at = timezone.now()

        from alarm.models import Entity

        updated = Entity.objects.filter(entity_id=entity_id, source="home_assistant").update(
            last_state=new_state_str,
            last_changed=changed_at,
            last_seen=seen_at,
        )
        if updated <= 0:
            return

        if old_state_str == new_state_str:
            return

        try:
            from alarm.websocket import broadcast_entity_sync

            broadcast_entity_sync(
                entities=[
                    {
                        "entity_id": entity_id,
                        "old_state": old_state_str,
                        "new_state": new_state_str,
                    }
                ]
            )
        except Exception:
            logger.warning("Entity sync broadcast failed", exc_info=True)

        try:
            from alarm.dispatcher import notify_entities_changed

            notify_entities_changed(
                source="home_assistant",
                entity_ids=[entity_id],
                changed_at=changed_at,
            )
        except Exception:
            logger.warning("Dispatcher notification failed", exc_info=True)


_stream = HomeAssistantStateStream()


def apply_runtime_settings_from_active_profile() -> None:
    _stream.apply_runtime_settings_from_active_profile()


def shutdown() -> None:
    _stream.stop()
