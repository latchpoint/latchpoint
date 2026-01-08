from __future__ import annotations

import json
import logging
import threading
from typing import Any

from django.core.cache import cache
from django.db import close_old_connections
from django.utils import timezone

from alarm.models import Entity
from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
from integrations_zigbee2mqtt.config import Zigbee2mqttSettings, normalize_zigbee2mqtt_settings
from integrations_zigbee2mqtt.entity_mapping import build_entities_for_z2m_device, extract_ieee_mapping
from integrations_zigbee2mqtt import status_store
from integrations_zigbee2mqtt.config import slugify_fragment
from transports_mqtt.manager import MqttNotReachable, mqtt_connection_manager


logger = logging.getLogger(__name__)

_CACHE_KEY_FRIENDLY_TO_IEEE = "zigbee2mqtt:friendly_to_ieee"
_CACHE_KEY_LAST_MAPPING_REFRESH_AT = "zigbee2mqtt:last_mapping_refresh_at"
_CACHE_KEY_LAST_DEVICES_RESPONSE_AT = "zigbee2mqtt:last_devices_response_at"
_CACHE_KEY_LAST_DEVICES_RESPONSE = "zigbee2mqtt:last_devices_response"
_CACHE_KEY_LAST_DEVICES_RESPONSE_TRANSACTION = "zigbee2mqtt:last_devices_response_transaction"
_CACHE_KEY_IEEE_ENTITY_IDS_PREFIX = "zigbee2mqtt:ieee_entity_ids:"

_init_lock = threading.Lock()
_initialized = False
_subscribed_wildcards: set[str] = set()
_subscribed_topics: set[str] = set()


def _parse_devices_response(payload: str) -> tuple[list[dict[str, Any]] | None, str | None, str | None]:
    """
    Parse a Zigbee2MQTT `bridge/response/devices` payload.

    Z2M may publish either a raw list or a dict wrapper depending on version/config.
    Returns: (devices_list_or_none, transaction_or_none, error_or_none)
    """
    try:
        obj = json.loads(payload) if payload else None
    except Exception as exc:
        return None, None, str(exc)

    if isinstance(obj, list):
        devices = [d for d in obj if isinstance(d, dict)]
        return devices, None, None

    if isinstance(obj, dict):
        transaction = None
        tx = obj.get("transaction")
        if isinstance(tx, str) and tx.strip():
            transaction = tx.strip()

        data = obj.get("data")
        if isinstance(data, list):
            devices = [d for d in data if isinstance(d, dict)]
            return devices, transaction, None

        # Some versions might use `devices` as a key.
        devices_obj = obj.get("devices")
        if isinstance(devices_obj, list):
            devices = [d for d in devices_obj if isinstance(d, dict)]
            return devices, transaction, None

        return None, transaction, "Invalid devices response."

    return None, None, "Invalid devices response."


def _cache_devices_response(*, devices: list[dict[str, Any]], transaction: str | None) -> None:
    cache.set(_CACHE_KEY_LAST_DEVICES_RESPONSE_AT, timezone.now().isoformat(), timeout=None)
    cache.set(_CACHE_KEY_LAST_DEVICES_RESPONSE, devices, timeout=None)
    cache.set(_CACHE_KEY_LAST_DEVICES_RESPONSE_TRANSACTION, transaction, timeout=None)


def _get_cached_devices_response() -> tuple[str | None, list[dict[str, Any]] | None, str | None]:
    at = cache.get(_CACHE_KEY_LAST_DEVICES_RESPONSE_AT)
    at_s = at if isinstance(at, str) else None
    devices = cache.get(_CACHE_KEY_LAST_DEVICES_RESPONSE)
    devices_list = devices if isinstance(devices, list) else None
    tx = cache.get(_CACHE_KEY_LAST_DEVICES_RESPONSE_TRANSACTION)
    tx_s = tx if isinstance(tx, str) else None
    return at_s, devices_list, tx_s


def _mqtt_enabled() -> bool:
    """Return True if MQTT is enabled and minimally configured in the active profile."""
    profile = get_active_settings_profile()
    mqtt_conn = get_setting_json(profile, "mqtt_connection") or {}
    return bool(isinstance(mqtt_conn, dict) and mqtt_conn.get("enabled") and mqtt_conn.get("host"))


def get_settings() -> Zigbee2mqttSettings:
    """Read and normalize Zigbee2MQTT settings from the active settings profile."""
    profile = get_active_settings_profile()
    raw = get_setting_json(profile, "zigbee2mqtt") or {}
    return normalize_zigbee2mqtt_settings(raw)


def _topic(*, base_topic: str, suffix: str) -> str:
    """Build a Zigbee2MQTT topic by joining base topic and suffix."""
    base = (base_topic or "").strip().strip("/")
    suf = (suffix or "").strip().lstrip("/")
    if not base:
        base = "zigbee2mqtt"
    return f"{base}/{suf}" if suf else base


def _entity_ids_cache_key(*, ieee: str) -> str:
    return f"{_CACHE_KEY_IEEE_ENTITY_IDS_PREFIX}{slugify_fragment(ieee)}"


def _known_entity_ids_for_ieee(*, ieee: str) -> set[str]:
    """
    Return the set of locally-known entity IDs for a Zigbee device (by ieee_address).

    This is used to avoid "best-effort" updates against multiple candidate entity IDs.
    """
    cache_key = _entity_ids_cache_key(ieee=ieee)
    cached = cache.get(cache_key)
    if isinstance(cached, list) and all(isinstance(v, str) for v in cached):
        return set(cached)
    if isinstance(cached, set) and all(isinstance(v, str) for v in cached):
        return set(cached)

    entity_ids = list(
        Entity.objects.filter(source="zigbee2mqtt", attributes__zigbee2mqtt__ieee_address=ieee).values_list(
            "entity_id", flat=True
        )
    )
    cache.set(cache_key, entity_ids, timeout=None)
    return set(entity_ids)


def _is_allowed(*, settings: Zigbee2mqttSettings, ieee: str, friendly_name: str) -> bool:
    """Return True if a device is allowed by allowlist/denylist settings."""
    if settings.denylist:
        if ieee in settings.denylist or friendly_name in settings.denylist:
            return False
    if settings.allowlist:
        return ieee in settings.allowlist or friendly_name in settings.allowlist
    return True


def initialize() -> None:
    """Register MQTT subscriptions and on-connect hooks (safe to call multiple times)."""
    global _initialized
    with _init_lock:
        if _initialized:
            return

        def _after_connect() -> None:
            """On-connect hook: refresh mapping and ensure subscriptions exist when enabled."""
            # Best-effort: refresh device mapping so ingest works without manual sync.
            refresh_device_mapping_async()

        mqtt_connection_manager.register_on_connect(_after_connect)

        settings = get_settings()
        if settings.enabled and _mqtt_enabled():
            _subscribe_for_ingest(settings=settings)
            refresh_device_mapping_async()

        _initialized = True


def apply_runtime_settings_from_active_profile() -> None:
    """Apply settings from the active profile by ensuring ingest subscriptions exist when enabled."""
    try:
        initialize()
        settings = get_settings()
        if settings.enabled and _mqtt_enabled():
            _subscribe_for_ingest(settings=settings)
            refresh_device_mapping_async()
    except Exception:
        return


def _subscribe_for_ingest(*, settings: Zigbee2mqttSettings) -> None:
    """Subscribe to Zigbee2MQTT wildcard topics for ingest and bridge state (idempotent)."""
    base = settings.base_topic
    wildcard = _topic(base_topic=base, suffix="+")
    bridge_state_topic = _topic(base_topic=base, suffix="bridge/state")
    devices_response_topic = _topic(base_topic=base, suffix="bridge/response/devices")
    devices_snapshot_topic = _topic(base_topic=base, suffix="bridge/devices")

    def _handle_message(*, topic: str, payload: str) -> None:
        """Per-message handler that reloads settings and routes payloads (best-effort)."""
        close_old_connections()
        try:
            if topic == bridge_state_topic:
                raw = (payload or "").strip()
                state = raw.lower()
                # Typical values are "online"/"offline". Mark seen regardless.
                status_store.mark_seen(state=state or None)
                return
            if topic == devices_response_topic:
                devices, transaction, err = _parse_devices_response(payload)
                if devices is None:
                    if err:
                        status_store.mark_error(error=str(err))
                    return
                _cache_devices_response(devices=devices, transaction=transaction)
                status_store.mark_seen(state="online")
                return
            if topic == devices_snapshot_topic:
                devices, transaction, err = _parse_devices_response(payload)
                if devices is None:
                    if err:
                        status_store.mark_error(error=str(err))
                    return
                _cache_devices_response(devices=devices, transaction=transaction)
                status_store.mark_seen(state="online")
                return
            current = get_settings()
            if not current.enabled:
                return
            _handle_z2m_message(settings=current, topic=topic, payload=payload)
        except Exception:
            return

    if wildcard not in _subscribed_wildcards:
        _subscribed_wildcards.add(wildcard)
        mqtt_connection_manager.subscribe(topic=wildcard, qos=0, callback=_handle_message)

    for topic in (bridge_state_topic, devices_response_topic, devices_snapshot_topic):
        if topic in _subscribed_topics:
            continue
        _subscribed_topics.add(topic)
        mqtt_connection_manager.subscribe(topic=topic, qos=0, callback=_handle_message)


def refresh_device_mapping_async(*, min_interval_seconds: int = 30) -> None:
    """
    Refreshes the friendly_name -> ieee mapping used for ingest.

    This is best-effort and intentionally does not upsert Entity rows (that's handled by explicit sync).
    """
    try:
        last = cache.get(_CACHE_KEY_LAST_MAPPING_REFRESH_AT)
        if isinstance(last, str):
            try:
                last_dt = timezone.datetime.fromisoformat(last)
                if timezone.now() - last_dt < timezone.timedelta(seconds=int(min_interval_seconds)):
                    return
            except Exception:
                pass
    except Exception:
        pass

    def _run() -> None:
        """Background worker to refresh the mapping without blocking the caller."""
        try:
            refresh_device_mapping_via_mqtt(timeout_seconds=3.0)
        except Exception:
            return

    threading.Thread(target=_run, daemon=True).start()


def refresh_device_mapping_via_mqtt(*, timeout_seconds: float = 3.0) -> dict[str, Any]:
    """
    Best-effort Zigbee2MQTT device mapping refresh:
    - publish `${base_topic}/bridge/request/devices`
    - wait for `${base_topic}/bridge/response/devices`
    - cache friendly_name -> ieee_address for ingest
    """
    settings = get_settings()
    if not settings.enabled:
        raise ValueError("Zigbee2MQTT is disabled.")
    if not _mqtt_enabled():
        raise ValueError("MQTT is not enabled/configured.")

    request_topic = _topic(base_topic=settings.base_topic, suffix="bridge/request/devices")
    # Ensure the shared response subscription is active before publishing.
    _subscribe_for_ingest(settings=settings)

    started_at = timezone.now()
    transaction = f"mapping:{started_at.timestamp()}"
    mqtt_connection_manager.publish(
        topic=request_topic,
        payload=json.dumps({"transaction": transaction}),
        qos=0,
        retain=False,
    )

    devices: list[dict[str, Any]] | None = None
    deadline = started_at + timezone.timedelta(seconds=float(timeout_seconds))
    while timezone.now() < deadline:
        at_s, cached_devices, _tx = _get_cached_devices_response()
        if at_s and cached_devices is not None:
            try:
                at_dt = timezone.datetime.fromisoformat(at_s)
                at_dt = timezone.make_aware(at_dt) if timezone.is_naive(at_dt) else at_dt
                if at_dt >= started_at:
                    devices = cached_devices
                    break
            except Exception:
                pass
        evt = threading.Event()
        evt.wait(timeout=0.05)

    if devices is None:
        # Fallback to the latest cached snapshot if available (e.g., Z2M publishes only `bridge/devices` retained).
        _at_s, cached_devices, _tx = _get_cached_devices_response()
        if cached_devices is None:
            raise TimeoutError("Timed out waiting for Zigbee2MQTT devices response.")
        devices = cached_devices

    mapping = extract_ieee_mapping(devices or [])
    cache.set(_CACHE_KEY_FRIENDLY_TO_IEEE, mapping, timeout=None)
    cache.set(_CACHE_KEY_LAST_MAPPING_REFRESH_AT, timezone.now().isoformat(), timeout=None)

    return {"ok": True, "devices": len(devices or []), "mapped": len(mapping)}


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


def _notify_dispatcher(*, entity_ids: list[str]) -> None:
    """Notify the dispatcher of entity changes (ADR 0057)."""
    if not entity_ids:
        return

    try:
        from alarm.dispatcher import notify_entities_changed
        notify_entities_changed(source="zigbee2mqtt", entity_ids=entity_ids)
    except Exception as exc:
        logger.debug("Dispatcher notification failed: %s", exc)


def _handle_z2m_message(*, settings: Zigbee2mqttSettings, topic: str, payload: str) -> None:
    """Parse and ingest a Zigbee2MQTT device message, updating Entities and applying mappings."""
    base = settings.base_topic.strip().strip("/")
    if not topic.startswith(f"{base}/"):
        return
    rest = topic[len(base) + 1 :]
    if rest.startswith("bridge/"):
        return
    if "/" in rest:
        # Ignore subtopics like `<device>/set` or `<device>/availability`.
        return

    # Device topics are `${base_topic}/${friendly_name}`
    friendly_name = rest.strip()
    if not friendly_name:
        return

    mapping = cache.get(_CACHE_KEY_FRIENDLY_TO_IEEE) or {}
    if not isinstance(mapping, dict):
        mapping = {}
    ieee = str(mapping.get(friendly_name) or "").strip()
    if not ieee:
        return

    if not _is_allowed(settings=settings, ieee=ieee, friendly_name=friendly_name):
        return

    try:
        data = json.loads(payload) if payload else {}
    except Exception:
        return
    if not isinstance(data, dict):
        return

    # Any valid Z2M device message implies Z2M is alive.
    try:
        status_store.mark_seen()
    except Exception:
        pass

    now = timezone.now()

    known_entity_ids = _known_entity_ids_for_ieee(ieee=ieee)
    changed_entity_ids: list[str] = []

    # Update action entity if present.
    action = data.get("action")
    if isinstance(action, str) and action.strip():
        action_entity_id = f"z2m_action.{slugify_fragment(ieee)}"
        if action_entity_id in known_entity_ids:
            Entity.objects.filter(entity_id=action_entity_id).update(
                last_state=action.strip(),
                last_changed=now,
                last_seen=now,
            )
            changed_entity_ids.append(action_entity_id)

    # Update entities for known keys.
    for key, value in data.items():
        key_str = str(key).strip()
        if not key_str:
            continue

        value_str = str(value)
        ieee_slug = slugify_fragment(ieee)
        key_slug = slugify_fragment(key_str)

        # Update only known entity IDs (avoid best-effort writes against multiple candidates).
        for entity_id in (
            f"z2m_binary_sensor.{ieee_slug}_{key_slug}",
            f"z2m_sensor.{ieee_slug}_{key_slug}",
            f"z2m_switch.{ieee_slug}_{key_slug}",
        ):
            if entity_id not in known_entity_ids:
                continue
            Entity.objects.filter(entity_id=entity_id).update(
                last_state=value_str,
                last_changed=now,
                last_seen=now,
            )
            changed_entity_ids.append(entity_id)

    # Notify dispatcher of entity changes (ADR 0057).
    if changed_entity_ids:
        _notify_dispatcher(entity_ids=changed_entity_ids)


def sync_devices_via_mqtt(*, timeout_seconds: float = 3.0) -> dict[str, Any]:
    """
    Best-effort Zigbee2MQTT inventory sync:
    - publish `${base_topic}/bridge/request/devices`
    - wait for `${base_topic}/bridge/response/devices`
    """
    initialize()
    settings = get_settings()
    if not settings.enabled:
        raise ValueError("Zigbee2MQTT is disabled.")
    if not _mqtt_enabled():
        raise ValueError("MQTT is not enabled/configured.")

    request_topic = _topic(base_topic=settings.base_topic, suffix="bridge/request/devices")
    # Ensure the shared response subscription is active before publishing.
    _subscribe_for_ingest(settings=settings)

    started_at = timezone.now()
    transaction = f"sync:{started_at.timestamp()}"
    try:
        mqtt_connection_manager.publish(
            topic=request_topic,
            payload=json.dumps({"transaction": transaction}),
            qos=0,
            retain=False,
        )
    except Exception as exc:
        try:
            status_store.mark_error(error=str(exc))
        except Exception:
            pass
        raise

    devices: list[dict[str, Any]] | None = None
    deadline = started_at + timezone.timedelta(seconds=float(timeout_seconds))
    while timezone.now() < deadline:
        at_s, cached_devices, _tx = _get_cached_devices_response()
        if at_s and cached_devices is not None:
            try:
                at_dt = timezone.datetime.fromisoformat(at_s)
                at_dt = timezone.make_aware(at_dt) if timezone.is_naive(at_dt) else at_dt
                if at_dt >= started_at:
                    devices = cached_devices
                    break
            except Exception:
                pass
        evt = threading.Event()
        evt.wait(timeout=0.05)

    if devices is None:
        # Fallback to the latest cached snapshot if available (e.g., Z2M publishes only `bridge/devices` retained).
        _at_s, cached_devices, _tx = _get_cached_devices_response()
        if cached_devices is None:
            exc = TimeoutError("Timed out waiting for Zigbee2MQTT devices response.")
            try:
                status_store.mark_error(error=str(exc))
            except Exception:
                pass
            raise exc
        devices = cached_devices

    # Update friendly_name -> ieee mapping cache.
    cache.set(_CACHE_KEY_FRIENDLY_TO_IEEE, extract_ieee_mapping(devices or []), timeout=None)

    upsert_count = 0
    entity_ids_by_ieee: dict[str, set[str]] = {}
    for d in devices or []:
        if not isinstance(d, dict):
            continue
        ieee = str(d.get("ieee_address") or "").strip()
        if ieee and ieee not in entity_ids_by_ieee:
            entity_ids_by_ieee[ieee] = set()
        for ent in build_entities_for_z2m_device(d):
            Entity.objects.update_or_create(
                entity_id=ent.entity_id,
                defaults={
                    "domain": ent.domain,
                    "name": ent.name,
                    "device_class": ent.device_class,
                    "attributes": ent.attributes,
                    "source": "zigbee2mqtt",
                },
            )
            upsert_count += 1
            if ieee:
                entity_ids_by_ieee[ieee].add(ent.entity_id)

    # Refresh per-device known entity-id caches for ingest correctness/performance.
    try:
        for ieee, ids in entity_ids_by_ieee.items():
            cache.set(_entity_ids_cache_key(ieee=ieee), sorted(ids), timeout=None)
    except Exception:
        pass

    devices_list = devices or []
    status_store.mark_sync(device_count=len(devices_list))
    return {"ok": True, "devices": len(devices_list), "entities_upserted": upsert_count}
