from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from alarm.models import Entity
from alarm.state_machine.settings import get_active_settings_profile, get_setting_json
from transports_mqtt.config import normalize_mqtt_connection, prepare_runtime_mqtt_connection
from transports_mqtt.manager import MqttNotReachable, mqtt_connection_manager

from alarm.gateways.mqtt import default_mqtt_gateway
from integrations_zigbee2mqtt.config import normalize_zigbee2mqtt_settings


class Zigbee2mqttGateway(Protocol):
    def set_entity_value(self, *, entity_id: str, value: Any) -> None:
        """Publish a Zigbee2MQTT control payload for a single exposed entity."""

        ...


def _topic(*, base_topic: str, suffix: str) -> str:
    base = (base_topic or "").strip().strip("/")
    suf = (suffix or "").strip().lstrip("/")
    if not base:
        base = "zigbee2mqtt"
    return f"{base}/{suf}" if suf else base


def _expose_property(expose: dict[str, Any]) -> str:
    prop = str(expose.get("property") or expose.get("name") or "").strip()
    return prop


def _flatten_exposes(exposes: object) -> list[dict[str, Any]]:
    """Flatten nested Zigbee2MQTT `exposes`/`features` structures into a single list."""
    if not isinstance(exposes, list):
        return []
    out: list[dict[str, Any]] = []
    for item in exposes:
        if not isinstance(item, dict):
            continue
        features = item.get("features")
        if isinstance(features, list):
            out.extend(_flatten_exposes(features))
        else:
            out.append(item)
    return out


def _expose_is_writable(expose: dict[str, Any]) -> bool:
    """
    Best-effort check for Zigbee2MQTT expose writability.

    Zigbee2MQTT commonly uses an integer bitmask for `access` where bit 2 indicates write.
    If access is missing, treat as writable (best-effort).
    """
    access = expose.get("access")
    if access is None:
        return True
    if not isinstance(access, int):
        return True
    return bool(access & 2)


def _normalize_state_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "on":
            return "ON"
        if lowered == "off":
            return "OFF"
    return value


def _validate_value_against_expose(*, prop: str, expose: dict[str, Any], value: Any) -> None:
    if not _expose_is_writable(expose):
        raise ValueError(f"Expose '{prop}' is not writable.")

    expose_type = str(expose.get("type") or "").lower()
    if prop == "state":
        if isinstance(value, (bool, str)):
            return
        raise ValueError("State must be a boolean or string.")

    if expose_type in {"numeric"}:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = expose.get("value_min")
            maximum = expose.get("value_max")
            if isinstance(minimum, (int, float)) and value < minimum:
                raise ValueError(f"Value for '{prop}' must be >= {minimum}.")
            if isinstance(maximum, (int, float)) and value > maximum:
                raise ValueError(f"Value for '{prop}' must be <= {maximum}.")
            return
        raise ValueError(f"Value for '{prop}' must be a number.")

    if expose_type in {"enum"}:
        values = expose.get("values")
        if isinstance(values, list) and values:
            allowed = {str(v) for v in values}
            if str(value) not in allowed:
                raise ValueError(f"Value for '{prop}' must be one of: {', '.join(sorted(allowed))}.")
        return

    if expose_type in {"text"}:
        if isinstance(value, str):
            return
        raise ValueError(f"Value for '{prop}' must be a string.")

    # Default: best-effort, but still enforce JSON-serializable primitives/objects.
    return


def _validate_payload_against_definition(*, payload: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    exposes = _flatten_exposes(definition.get("exposes"))
    exposes_by_prop: dict[str, dict[str, Any]] = {}
    for e in exposes:
        prop = _expose_property(e)
        if prop:
            exposes_by_prop[prop] = e

    normalized: dict[str, Any] = {}
    for prop, raw_value in payload.items():
        if prop not in exposes_by_prop:
            raise ValueError(f"Unknown Zigbee2MQTT property '{prop}'.")
        expose = exposes_by_prop[prop]
        value = _normalize_state_value(raw_value) if prop == "state" else raw_value
        _validate_value_against_expose(prop=prop, expose=expose, value=value)
        normalized[prop] = value
    return normalized


@dataclass(frozen=True)
class DefaultZigbee2mqttGateway:
    def set_entity_value(self, *, entity_id: str, value: Any) -> None:
        profile = get_active_settings_profile()

        mqtt_raw = get_setting_json(profile, "mqtt_connection") or {}
        mqtt_settings = normalize_mqtt_connection(mqtt_raw)
        if not bool(mqtt_settings.get("enabled")):
            raise ValueError("MQTT is disabled.")
        default_mqtt_gateway.apply_settings(settings=prepare_runtime_mqtt_connection(mqtt_raw))

        z2m_raw = get_setting_json(profile, "zigbee2mqtt") or {}
        z2m_settings = normalize_zigbee2mqtt_settings(z2m_raw)
        if not z2m_settings.enabled:
            raise ValueError("Zigbee2MQTT is disabled.")

        entity = Entity.objects.filter(entity_id=entity_id).first()
        if not entity:
            raise ValueError("Unknown entity_id.")
        if entity.source != "zigbee2mqtt":
            raise ValueError("Entity is not a Zigbee2MQTT entity.")

        attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
        z2m = attrs.get("zigbee2mqtt") if isinstance(attrs.get("zigbee2mqtt"), dict) else {}
        friendly_name = str(z2m.get("friendly_name") or "").strip()
        ieee_address = str(z2m.get("ieee_address") or "").strip()
        if not friendly_name and not ieee_address:
            raise ValueError("Missing Zigbee2MQTT friendly_name/ieee_address on entity.")
        target_name = friendly_name or ieee_address

        denylist = {str(v).strip() for v in (z2m_settings.denylist or []) if str(v).strip()}
        allowlist = {str(v).strip() for v in (z2m_settings.allowlist or []) if str(v).strip()}
        if denylist and (target_name in denylist or ieee_address in denylist):
            raise ValueError("Zigbee2MQTT device is denylisted.")
        if allowlist and (target_name not in allowlist and (not ieee_address or ieee_address not in allowlist)):
            raise ValueError("Zigbee2MQTT device is not allowlisted.")

        expose = z2m.get("expose") if isinstance(z2m.get("expose"), dict) else None
        definition = z2m.get("definition") if isinstance(z2m.get("definition"), dict) else {}
        if isinstance(value, dict):
            payload_obj = _validate_payload_against_definition(payload=value, definition=definition)
        else:
            if not expose:
                raise ValueError("Missing Zigbee2MQTT expose metadata on entity.")
            prop = _expose_property(expose)
            if not prop:
                raise ValueError("Missing expose property/name.")
            payload_value = _normalize_state_value(value) if prop == "state" else value
            _validate_value_against_expose(prop=prop, expose=expose, value=payload_value)
            payload_obj = {prop: payload_value}

        topic = _topic(base_topic=z2m_settings.base_topic, suffix=f"{target_name}/set")
        payload = json.dumps(payload_obj)
        try:
            mqtt_connection_manager.publish(topic=topic, payload=payload, qos=0, retain=False)
        except MqttNotReachable as exc:
            raise RuntimeError("MQTT is not reachable.") from exc


default_zigbee2mqtt_gateway: Zigbee2mqttGateway = DefaultZigbee2mqttGateway()
