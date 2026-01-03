from __future__ import annotations

from typing import Any

from alarm.gateways.home_assistant import HomeAssistantGateway, default_home_assistant_gateway


def fetch_available_locks(
    *,
    ha_gateway: HomeAssistantGateway = default_home_assistant_gateway,
) -> list[dict[str, Any]]:
    """
    Fetch available lock entities from Home Assistant.

    Returns a list of lock entities with entity_id, name, and state.
    Used to populate the lock selection UI.
    """
    return [entity for entity in ha_gateway.list_entities() if entity.get("domain") == "lock"]
