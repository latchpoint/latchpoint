from __future__ import annotations

from django.db.models import Max

from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway
from alarm.models import AlarmEvent, AlarmEventType, Entity, RuleEntityRef, Sensor


def _entity_states_from_db(entity_ids: set[str]) -> dict[str, str | None]:
    """Return entity_id -> last_state from the DB for the given set of entity IDs."""
    if not entity_ids:
        return {}
    return dict(Entity.objects.filter(entity_id__in=entity_ids).values_list("entity_id", "last_state"))


def _overlay_entity_states_from_home_assistant(
    *,
    entity_state_by_entity_id: dict[str, str | None],
    entity_ids: set[str],
    ha_gateway: HomeAssistantGateway,
) -> None:
    """Overlay live entity states from Home Assistant onto the provided state map (best-effort)."""
    if not entity_ids:
        return

    status_obj = ha_gateway.get_status()
    if not status_obj.configured or not status_obj.reachable:
        return

    try:
        for item in ha_gateway.list_entities():
            if not isinstance(item, dict):
                continue
            entity_id = item.get("entity_id")
            if not isinstance(entity_id, str) or entity_id not in entity_ids:
                continue
            state = item.get("state")
            entity_state_by_entity_id[entity_id] = state if isinstance(state, str) else None
    except Exception:
        # Fall back to DB-backed states when HA can't be queried live.
        return


def _used_entity_ids_in_enabled_rules() -> set[str]:
    """Return the set of entity_ids referenced by enabled rules."""
    return set(RuleEntityRef.objects.filter(rule__enabled=True).values_list("entity__entity_id", flat=True))


def _last_triggered_by_sensor_id(*, sensors: list[Sensor]) -> dict[int, object]:
    """Return sensor_id -> last triggered timestamp for the provided sensors."""
    if not sensors:
        return {}
    return dict(
        AlarmEvent.objects.filter(
            event_type=AlarmEventType.SENSOR_TRIGGERED,
            sensor__in=sensors,
        )
        .values("sensor_id")
        .annotate(last_ts=Max("timestamp"))
        .values_list("sensor_id", "last_ts")
    )


def sensor_list_serializer_context(
    *,
    sensors: list[Sensor],
    prefer_home_assistant_live_state: bool = True,
    ha_gateway: HomeAssistantGateway = default_home_assistant_gateway,
) -> dict:
    """Build serializer context for listing sensors (entity states, last triggered, rule usage)."""
    entity_ids = {(s.entity_id or "").strip() for s in sensors if (s.entity_id or "").strip()}
    entity_state_by_entity_id = _entity_states_from_db(entity_ids)
    if prefer_home_assistant_live_state:
        _overlay_entity_states_from_home_assistant(
            entity_state_by_entity_id=entity_state_by_entity_id,
            entity_ids=entity_ids,
            ha_gateway=ha_gateway,
        )

    return {
        "entity_state_by_entity_id": entity_state_by_entity_id,
        "last_triggered_by_sensor_id": _last_triggered_by_sensor_id(sensors=sensors),
        "used_entity_ids_in_rules": _used_entity_ids_in_enabled_rules(),
    }


def sensor_detail_serializer_context(
    *,
    sensor: Sensor,
    prefer_home_assistant_live_state: bool = True,
    ha_gateway: HomeAssistantGateway = default_home_assistant_gateway,
) -> dict:
    """Build serializer context for a single sensor (entity state, last triggered, rule usage)."""
    entity_ids = {(sensor.entity_id or "").strip()} if (sensor.entity_id or "").strip() else set()
    entity_state_by_entity_id = _entity_states_from_db(entity_ids)
    if prefer_home_assistant_live_state:
        _overlay_entity_states_from_home_assistant(
            entity_state_by_entity_id=entity_state_by_entity_id,
            entity_ids=entity_ids,
            ha_gateway=ha_gateway,
        )

    return {
        "entity_state_by_entity_id": entity_state_by_entity_id,
        "last_triggered_by_sensor_id": _last_triggered_by_sensor_id(sensors=[sensor]),
        "used_entity_ids_in_rules": _used_entity_ids_in_enabled_rules(),
    }
