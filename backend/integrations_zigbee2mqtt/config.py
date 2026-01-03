from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

def _as_list(value: object) -> list[object]:
    """Coerce a value into a list, returning [] for non-lists."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return []


def _as_dict(value: object) -> dict[str, Any]:
    """Coerce a value into a dict, returning {} for non-dicts."""
    if isinstance(value, dict):
        return value
    return {}


@dataclass(frozen=True)
class Zigbee2mqttSettings:
    enabled: bool
    base_topic: str
    allowlist: list[object]
    denylist: list[object]
    run_rules_on_event: bool
    run_rules_debounce_seconds: int
    run_rules_max_per_minute: int
    run_rules_kinds: list[str]


DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "base_topic": "zigbee2mqtt",
    "allowlist": [],
    "denylist": [],
    "run_rules_on_event": False,
    "run_rules_debounce_seconds": 2,
    "run_rules_max_per_minute": 30,
    "run_rules_kinds": ["trigger"],
}


def normalize_zigbee2mqtt_settings(raw: object) -> Zigbee2mqttSettings:
    """Normalize a raw JSON settings object into a typed `Zigbee2mqttSettings`."""
    data = _as_dict(raw)
    base_topic = str(data.get("base_topic") or DEFAULT_SETTINGS["base_topic"]).strip()
    if not base_topic:
        base_topic = str(DEFAULT_SETTINGS["base_topic"])

    # Default allow-all behavior; lists are used only when populated.
    allowlist = _as_list(data.get("allowlist"))
    denylist = _as_list(data.get("denylist"))

    run_rules_on_event = bool(data.get("run_rules_on_event", DEFAULT_SETTINGS["run_rules_on_event"]))
    debounce_raw = data.get("run_rules_debounce_seconds", DEFAULT_SETTINGS["run_rules_debounce_seconds"])
    try:
        run_rules_debounce_seconds = int(debounce_raw)
    except Exception:
        run_rules_debounce_seconds = int(DEFAULT_SETTINGS["run_rules_debounce_seconds"])
    if run_rules_debounce_seconds < 0:
        run_rules_debounce_seconds = 0

    max_raw = data.get("run_rules_max_per_minute", DEFAULT_SETTINGS["run_rules_max_per_minute"])
    try:
        run_rules_max_per_minute = int(max_raw)
    except Exception:
        run_rules_max_per_minute = int(DEFAULT_SETTINGS["run_rules_max_per_minute"])
    if run_rules_max_per_minute < 0:
        run_rules_max_per_minute = 0

    kinds_raw = data.get("run_rules_kinds", DEFAULT_SETTINGS["run_rules_kinds"])
    run_rules_kinds: list[str] = []
    if isinstance(kinds_raw, list):
        run_rules_kinds = [str(k).strip() for k in kinds_raw if isinstance(k, str) and str(k).strip()]
    if not run_rules_kinds:
        run_rules_kinds = list(DEFAULT_SETTINGS["run_rules_kinds"])

    return Zigbee2mqttSettings(
        enabled=bool(data.get("enabled", False)),
        base_topic=base_topic,
        allowlist=allowlist,
        denylist=denylist,
        run_rules_on_event=run_rules_on_event,
        run_rules_debounce_seconds=run_rules_debounce_seconds,
        run_rules_max_per_minute=run_rules_max_per_minute,
        run_rules_kinds=run_rules_kinds,
    )


def mask_zigbee2mqtt_settings(raw: object) -> dict[str, Any]:
    """Return a safe-for-API view of Zigbee2MQTT settings."""
    normalized = normalize_zigbee2mqtt_settings(raw)
    return {
        "enabled": normalized.enabled,
        "base_topic": normalized.base_topic,
        "allowlist": normalized.allowlist,
        "denylist": normalized.denylist,
        "run_rules_on_event": normalized.run_rules_on_event,
        "run_rules_debounce_seconds": normalized.run_rules_debounce_seconds,
        "run_rules_max_per_minute": normalized.run_rules_max_per_minute,
        "run_rules_kinds": normalized.run_rules_kinds,
    }


_slug_re = re.compile(r"[^a-z0-9_]+")


def slugify_fragment(value: str) -> str:
    """Slugify a fragment for use in entity_id parts (lowercase + underscores)."""
    value = (value or "").strip().lower()
    value = value.replace("-", "_").replace(" ", "_")
    value = _slug_re.sub("_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value
