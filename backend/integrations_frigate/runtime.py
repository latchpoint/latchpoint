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
_CACHE_LAST_RULES_RUN_AT = f"{_PREFIX}last_rules_run_at"
_CACHE_RULES_RUNS_PER_MINUTE = f"{_PREFIX}rules_runs_per_minute"
_CACHE_RULES_RUNS_TRIGGERED = f"{_PREFIX}rules_runs_triggered"
_CACHE_RULES_RUNS_SKIPPED_DEBOUNCE = f"{_PREFIX}rules_runs_skipped_debounce"
_CACHE_RULES_RUNS_SKIPPED_RATE_LIMIT = f"{_PREFIX}rules_runs_skipped_rate_limit"

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


def get_rules_run_stats() -> dict[str, object]:
    """Return coarse rules-run counters for UI/debug."""
    return {
        "last_rules_run_at": cache.get(_CACHE_LAST_RULES_RUN_AT),
        "triggered": cache.get(_CACHE_RULES_RUNS_TRIGGERED) or 0,
        "skipped_debounce": cache.get(_CACHE_RULES_RUNS_SKIPPED_DEBOUNCE) or 0,
        "skipped_rate_limit": cache.get(_CACHE_RULES_RUNS_SKIPPED_RATE_LIMIT) or 0,
    }


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


def _incr_cache_counter(key: str, *, ttl_seconds: int | None = None) -> int:
    """Increment an integer cache counter and return the new value (best-effort)."""
    try:
        value = cache.get(key)
        if isinstance(value, int):
            next_val = value + 1
        else:
            next_val = 1
        cache.set(key, next_val, timeout=ttl_seconds)
        return next_val
    except Exception:
        return 0


def _maybe_trigger_rules_run(*, settings: FrigateSettings, camera: str, event_id: str) -> None:
    """Optionally run the rules engine in response to an event, with dedupe/debounce/rate limits."""
    if not settings.run_rules_on_event:
        return
    camera = (camera or "").strip()
    event_id = (event_id or "").strip()

    if event_id:
        dedupe_key = f"{_PREFIX}rules_ran_for_event:{event_id}"
        if cache.get(dedupe_key):
            return
        cache.set(dedupe_key, True, timeout=max(60, int(settings.retention_seconds)))

    debounce = int(settings.run_rules_debounce_seconds or 0)
    if debounce < 0:
        debounce = 0

    now = timezone.now()
    if debounce:
        if camera:
            last_cam_key = f"{_PREFIX}last_rules_run_at:{camera}"
            last_cam = cache.get(last_cam_key)
            if isinstance(last_cam, str):
                try:
                    last_dt = timezone.datetime.fromisoformat(last_cam)
                    last_dt = timezone.make_aware(last_dt) if timezone.is_naive(last_dt) else last_dt
                    if now - last_dt < timezone.timedelta(seconds=debounce):
                        _incr_cache_counter(_CACHE_RULES_RUNS_SKIPPED_DEBOUNCE, ttl_seconds=None)
                        return
                except Exception:
                    pass
            cache.set(last_cam_key, now.isoformat(), timeout=None)

        last = cache.get(_CACHE_LAST_RULES_RUN_AT)
        if isinstance(last, str):
            try:
                last_dt = timezone.datetime.fromisoformat(last)
                last_dt = timezone.make_aware(last_dt) if timezone.is_naive(last_dt) else last_dt
                if now - last_dt < timezone.timedelta(seconds=debounce):
                    _incr_cache_counter(_CACHE_RULES_RUNS_SKIPPED_DEBOUNCE, ttl_seconds=None)
                    return
            except Exception:
                pass
        cache.set(_CACHE_LAST_RULES_RUN_AT, now.isoformat(), timeout=None)

    max_per_min = int(settings.run_rules_max_per_minute or 0)
    if max_per_min > 0:
        current = _incr_cache_counter(_CACHE_RULES_RUNS_PER_MINUTE, ttl_seconds=60)
        if current > max_per_min:
            _incr_cache_counter(_CACHE_RULES_RUNS_SKIPPED_RATE_LIMIT, ttl_seconds=None)
            return

    def _run() -> None:
        """Background worker that runs rules (filtered by allowed kinds if configured)."""
        close_old_connections()
        try:
            from alarm import rules_engine
            from alarm.rules.repositories import RuleEngineRepositories, default_rule_engine_repositories

            repos = default_rule_engine_repositories()
            allowed_kinds = set(settings.run_rules_kinds or [])
            if allowed_kinds:
                original = repos

                def _list_enabled_rules_filtered():
                    """Filter enabled rules to only those whose kind is allowed by settings."""
                    return [r for r in original.list_enabled_rules() if getattr(r, "kind", None) in allowed_kinds]

                repos = RuleEngineRepositories(
                    list_enabled_rules=_list_enabled_rules_filtered,
                    entity_state_map=original.entity_state_map,
                    due_runtimes=original.due_runtimes,
                    ensure_runtime=original.ensure_runtime,
                    frigate_is_available=original.frigate_is_available,
                    list_frigate_detections=original.list_frigate_detections,
                    get_alarm_state=original.get_alarm_state,
                )

            rules_engine.run_rules(actor_user=None, repos=repos)
            _incr_cache_counter(_CACHE_RULES_RUNS_TRIGGERED, ttl_seconds=None)
        except Exception as exc:
            logger.warning("Failed to run rules on Frigate event ingest: %s", exc)

    threading.Thread(target=_run, daemon=True).start()


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

    try:
        _maybe_trigger_rules_run(settings=settings, camera=parsed.camera, event_id=parsed.event_id)
    except Exception:
        return
