from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from alarm.models import Entity


def sync_entities_from_home_assistant(*, items: list[dict], now=None) -> dict:
    """Upsert entities from Home Assistant payload items into the local entity registry."""
    now = now or timezone.now()
    imported = 0
    updated = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        entity_id = item.get("entity_id")
        domain = item.get("domain")
        name = item.get("name")
        if not isinstance(entity_id, str) or "." not in entity_id:
            continue
        if not isinstance(domain, str) or not domain:
            domain = entity_id.split(".", 1)[0]
        if not isinstance(name, str) or not name:
            name = entity_id

        last_changed_raw = item.get("last_changed")
        last_changed = parse_datetime(last_changed_raw) if isinstance(last_changed_raw, str) else None

        attributes: dict = {
            "unit_of_measurement": item.get("unit_of_measurement"),
        }
        zwavejs = item.get("zwavejs")
        if isinstance(zwavejs, dict):
            # Keep this small: just enough to link HA lock entities back to a Z-Wave JS node.
            node_id = zwavejs.get("node_id")
            if isinstance(node_id, str) and node_id.isdigit():
                node_id = int(node_id)
            home_id = zwavejs.get("home_id")
            if isinstance(home_id, str) and home_id.isdigit():
                home_id = int(home_id)
            zwavejs_out = {}
            if isinstance(node_id, int):
                zwavejs_out["node_id"] = node_id
            if isinstance(home_id, int):
                zwavejs_out["home_id"] = home_id
            if zwavejs_out:
                attributes["zwavejs"] = zwavejs_out

        defaults = {
            "domain": domain,
            "name": name,
            "device_class": item.get("device_class") if isinstance(item.get("device_class"), str) else None,
            "last_state": item.get("state") if isinstance(item.get("state"), str) else None,
            "last_changed": last_changed,
            "last_seen": now,
            "attributes": attributes,
            "source": "home_assistant",
        }

        _, created = Entity.objects.update_or_create(entity_id=entity_id, defaults=defaults)
        imported += 1 if created else 0
        updated += 0 if created else 1

    return {"imported": imported, "updated": updated, "timestamp": now}
