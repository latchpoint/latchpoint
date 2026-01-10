from __future__ import annotations

import json
import logging
import threading
from typing import Any

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
from integrations_frigate.config import FrigateSettings, normalize_frigate_settings
from integrations_frigate.models import FrigateDetection
from integrations_frigate.parsing import parse_frigate_events_payload
from transports_mqtt.manager import mqtt_connection_manager


logger = logging.getLogger(__name__)

_PREFIX = "frigate:"
_CACHE_LAST_INGEST_AT = f"{_PREFIX}last_ingest_at"
_CACHE_LAST_ERROR = f"{_PREFIX}last_error"
_CACHE_AVAILABILITY_STATE = f"{_PREFIX}availability_state"
_CACHE_LAST_PRUNE_AT = f"{_PREFIX}last_prune_at"

_init_lock = threading.Lock()
_initialized = False
_subscribed_topics: set[str] = set()


def _mqtt_enabled() -> bool:
    """Return True if MQTT is enabled and minimally configured in the active profile."""
    profile = get_active_settings_profile()
    mqtt_conn = get_setting_json(profile, "mqtt_connection") or {}
    return bool(isinstance(mqtt_conn, dict) and mqtt_conn.get("enabled") and mqtt_conn.get("host"))


def get_settings() -> FrigateSettings:
    """Read and normalize Frigate settings from the active settings profile."""
    profile = get_active_settings_profile()
    raw = get_setting_json(profile, "frigate") or {}
    return normalize_frigate_settings(raw)


def mark_error(error: str) -> None:
    """Persist the last ingest error (best-effort)."""
    cache.set(_CACHE_LAST_ERROR, str(error), timeout=None)


def mark_ingest() -> None:
    """Record a successful ingest and clear the last error (best-effort)."""
    cache.set(_CACHE_LAST_INGEST_AT, timezone.now().isoformat(), timeout=None)
    cache.set(_CACHE_LAST_ERROR, None, timeout=None)


def get_last_ingest_at() -> str | None:
    """Return the last ingest timestamp string, if known."""
    val = cache.get(_CACHE_LAST_INGEST_AT)
    return val if isinstance(val, str) else None


def get_last_error() -> str | None:
    """Return the last ingest error string, if any."""
    val = cache.get(_CACHE_LAST_ERROR)
    return val if isinstance(val, str) else None


def mark_availability_state(state: str) -> None:
    """Record the Frigate availability state from MQTT (online/offline)."""
    cache.set(_CACHE_AVAILABILITY_STATE, state.lower().strip(), timeout=None)


def get_availability_state() -> str | None:
    """Return the last known Frigate availability state, if any."""
    val = cache.get(_CACHE_AVAILABILITY_STATE)
    return val if isinstance(val, str) else None


def is_available(*, now=None) -> bool:
    """Return True if Frigate is available based on the frigate/available MQTT topic."""
    settings = get_settings()
    if not settings.enabled:
        return False
    if not _mqtt_enabled():
        return False
    if not mqtt_connection_manager.get_status().connected:
        return False
    # Consider available unless explicitly "offline"
    # (None means no message received yet - assume available)
    return get_availability_state() != "offline"


def initialize() -> None:
    """Register MQTT subscriptions and on-connect hooks (safe to call multiple times)."""
    global _initialized
    with _init_lock:
        if _initialized:
            return

        def _after_connect() -> None:
            """On-connect hook: ensure subscriptions are registered when enabled."""
            settings = get_settings()
            if settings.enabled and _mqtt_enabled():
                _subscribe(settings=settings)

        mqtt_connection_manager.register_on_connect(_after_connect)

        settings = get_settings()
        if settings.enabled and _mqtt_enabled():
            _subscribe(settings=settings)

        _initialized = True


def apply_runtime_settings_from_active_profile() -> None:
    """Apply settings from the active profile by ensuring subscriptions exist when enabled."""
    try:
        initialize()
        settings = get_settings()
        if settings.enabled and _mqtt_enabled():
            _subscribe(settings=settings)
    except Exception:
        return


def prune_old_detections(*, retention_seconds: int, min_interval_seconds: int = 60) -> None:
    """Prune stored detections older than retention, limiting work by a minimum interval."""
    try:
        last = cache.get(_CACHE_LAST_PRUNE_AT)
        if isinstance(last, str):
            try:
                last_dt = timezone.datetime.fromisoformat(last)
                last_dt = timezone.make_aware(last_dt) if timezone.is_naive(last_dt) else last_dt
                if timezone.now() - last_dt < timezone.timedelta(seconds=int(min_interval_seconds)):
                    return
            except Exception:
                pass
    except Exception:
        pass

    cutoff = timezone.now() - timezone.timedelta(seconds=int(retention_seconds))
    FrigateDetection.objects.filter(observed_at__lt=cutoff).delete()
    cache.set(_CACHE_LAST_PRUNE_AT, timezone.now().isoformat(), timeout=None)


def _notify_dispatcher(*, camera: str, event_id: str, changed_at=None) -> None:
    """Notify the dispatcher of Frigate detection (ADR 0057)."""
    try:
        from alarm.dispatcher import notify_entities_changed

        # Use synthetic entity ID for Frigate detection routing (ADR 0059).
        # Per-camera allows dispatcher to route only impacted rules.
        camera_key = (camera or "").strip()
        synthetic_entity_id = (
            f"__frigate.person_detected:{camera_key}" if camera_key else "__frigate.person_detected"
        )
        notify_entities_changed(
            source="frigate:detection",
            entity_ids=[synthetic_entity_id],
            changed_at=changed_at,
        )
    except Exception as exc:
        logger.debug("Dispatcher notification failed: %s", exc)


def _subscribe(*, settings: FrigateSettings) -> None:
    """Subscribe to the configured Frigate MQTT events topic and availability topic (idempotent)."""
    # Subscribe to events topic
    topic = settings.events_topic
    if topic not in _subscribed_topics:
        _subscribed_topics.add(topic)

        def _handle_message(*, topic: str, payload: str) -> None:
            """Per-message handler that reloads settings and ingests the payload (best-effort)."""
            close_old_connections()
            try:
                current = get_settings()
                if not current.enabled:
                    return
                _handle_frigate_message(settings=current, topic=topic, payload=payload)
            except Exception:
                return

        mqtt_connection_manager.subscribe(topic=topic, qos=0, callback=_handle_message)

    # Subscribe to availability topic
    avail_topic = "frigate/available"
    if avail_topic not in _subscribed_topics:
        _subscribed_topics.add(avail_topic)

        def _handle_availability(*, topic: str, payload: str) -> None:
            """Handle Frigate availability state messages (online/offline)."""
            try:
                mark_availability_state(payload)
            except Exception:
                pass

        mqtt_connection_manager.subscribe(topic=avail_topic, qos=0, callback=_handle_availability)


def _handle_frigate_message(*, settings: FrigateSettings, topic: str, payload: str) -> None:
    """Parse a Frigate event payload, persist detections, and optionally trigger rules."""
    try:
        obj = json.loads(payload) if payload else None
    except Exception as exc:
        mark_error(f"Invalid JSON payload: {exc}")
        return

    parsed = parse_frigate_events_payload(obj)
    if not parsed:
        return
    if parsed.label != "person":
        return

    try:
        if parsed.event_id:
            FrigateDetection.objects.update_or_create(
                provider=parsed.provider,
                event_id=parsed.event_id,
                defaults={
                    "label": parsed.label,
                    "camera": parsed.camera,
                    "zones": parsed.zones,
                    "confidence_pct": parsed.confidence_pct,
                    "observed_at": parsed.observed_at,
                    "source_topic": topic,
                    "raw": parsed.raw,
                },
            )
        else:
            FrigateDetection.objects.create(
                provider=parsed.provider,
                event_id="",
                label=parsed.label,
                camera=parsed.camera,
                zones=parsed.zones,
                confidence_pct=parsed.confidence_pct,
                observed_at=parsed.observed_at,
                source_topic=topic,
                raw=parsed.raw,
            )
        mark_ingest()
    except Exception as exc:
        mark_error(str(exc))
        return

    try:
        prune_old_detections(retention_seconds=settings.retention_seconds)
    except Exception:
        return

    # Notify dispatcher of Frigate detection (ADR 0057).
    observed_at = parsed.observed_at if getattr(parsed, "observed_at", None) is not None else timezone.now()
    _notify_dispatcher(camera=parsed.camera, event_id=parsed.event_id, changed_at=observed_at)
