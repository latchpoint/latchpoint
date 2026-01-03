from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from integrations_zigbee2mqtt.config import slugify_fragment


@dataclass(frozen=True)
class Z2mExposedEntity:
    entity_id: str
    domain: str
    name: str
    device_class: str | None
    attributes: dict[str, Any]


def _flatten_exposes(exposes: object) -> list[dict[str, Any]]:
    """Flatten nested Zigbee2MQTT `exposes`/`features` structures into a single list."""
    if not isinstance(exposes, list):
        return []
    out: list[dict[str, Any]] = []
    for item in exposes:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("features"), list):
            out.extend(_flatten_exposes(item.get("features")))
        else:
            out.append(item)
    return out


def _device_class_for(expose: dict[str, Any]) -> str | None:
    """Infer a Home Assistant-like device_class from an expose descriptor."""
    name = str(expose.get("name") or expose.get("property") or "").lower()
    if name in {"contact", "door", "window", "opening"}:
        return "door"
    if name in {"occupancy", "motion", "presence"}:
        return "motion"
    if name in {"smoke"}:
        return "smoke"
    if name in {"water_leak", "moisture", "leak"}:
        return "water"
    return None


def _domain_for(expose: dict[str, Any]) -> str:
    """Infer an entity domain for an expose descriptor."""
    t = str(expose.get("type") or "").lower()
    name = str(expose.get("name") or expose.get("property") or "").lower()
    if name == "action":
        return "action"
    if t in {"binary"}:
        return "binary_sensor"
    if t in {"numeric", "enum", "text"}:
        return "sensor"
    if t in {"switch", "light"}:
        return "switch"
    return "sensor"


def _entity_id(*, ieee: str, domain: str, prop: str) -> str:
    """Build a stable entity_id string for a Zigbee2MQTT device expose."""
    ieee_slug = slugify_fragment(ieee)
    prop_slug = slugify_fragment(prop)
    if domain == "binary_sensor":
        return f"z2m_binary_sensor.{ieee_slug}_{prop_slug}"
    if domain == "sensor":
        return f"z2m_sensor.{ieee_slug}_{prop_slug}"
    if domain == "switch":
        return f"z2m_switch.{ieee_slug}_{prop_slug}"
    if domain == "action":
        return f"z2m_action.{ieee_slug}"
    return f"z2m.{ieee_slug}_{prop_slug}"


def build_entities_for_z2m_device(device: dict[str, Any]) -> list[Z2mExposedEntity]:
    """Build exposed entities for a Zigbee2MQTT device payload."""
    ieee = str(device.get("ieee_address") or "").strip()
    friendly_name = str(device.get("friendly_name") or "").strip() or ieee
    definition = device.get("definition") if isinstance(device.get("definition"), dict) else {}
    exposes = _flatten_exposes(definition.get("exposes"))

    entities: list[Z2mExposedEntity] = []
    for expose in exposes:
        prop = str(expose.get("property") or expose.get("name") or "").strip()
        if not prop:
            continue
        domain = _domain_for(expose)
        entity_id = _entity_id(ieee=ieee, domain=domain, prop=prop)
        name = f"{friendly_name} {prop}".strip()
        attributes = {
            "zigbee2mqtt": {
                "ieee_address": ieee,
                "friendly_name": str(device.get("friendly_name") or ""),
                "definition": definition,
                "expose": expose,
            }
        }
        entities.append(
            Z2mExposedEntity(
                entity_id=entity_id,
                domain=domain,
                name=name,
                device_class=_device_class_for(expose),
                attributes=attributes,
            )
        )

    # If the device can emit action events, create a stable action entity.
    has_action = any(str(e.get("name") or e.get("property") or "").lower() == "action" for e in exposes)
    if has_action and ieee:
        entities.append(
            Z2mExposedEntity(
                entity_id=_entity_id(ieee=ieee, domain="action", prop="action"),
                domain="action",
                name=f"{friendly_name} action".strip(),
                device_class=None,
                attributes={
                    "zigbee2mqtt": {
                        "ieee_address": ieee,
                        "friendly_name": str(device.get("friendly_name") or ""),
                        "definition": definition,
                    }
                },
            )
        )

    # De-dupe by entity_id (last write wins).
    by_id: dict[str, Z2mExposedEntity] = {e.entity_id: e for e in entities}
    return list(by_id.values())


def extract_ieee_mapping(devices: Iterable[dict[str, Any]]) -> dict[str, str]:
    """
    Returns mapping of friendly_name -> ieee_address for Z2M device topics.
    """
    out: dict[str, str] = {}
    for d in devices:
        if not isinstance(d, dict):
            continue
        friendly = str(d.get("friendly_name") or "").strip()
        ieee = str(d.get("ieee_address") or "").strip()
        if friendly and ieee:
            out[friendly] = ieee
    return out
