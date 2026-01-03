from __future__ import annotations

from typing import Any

from django.utils import timezone

from alarm.gateways.zwavejs import ZwavejsGateway
from alarm.models import Entity
from integrations_zwavejs.manager import build_zwavejs_entity_id, infer_entity_domain, normalize_entity_state


def _extract_nodes(controller_state: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Best-effort extraction of a nodes list from zwave-js-server state shapes.
    """

    state = controller_state.get("state") if isinstance(controller_state.get("state"), dict) else controller_state
    nodes = state.get("nodes") if isinstance(state, dict) else None
    if isinstance(nodes, list):
        return nodes
    if isinstance(nodes, dict):
        out: list[dict[str, Any]] = []
        for key, value in nodes.items():
            if not isinstance(value, dict):
                continue
            if "id" in value or "nodeId" in value:
                out.append(value)
                continue
            node_id: int | None = None
            if isinstance(key, int):
                node_id = key
            elif isinstance(key, str) and key.isdigit():
                node_id = int(key)
            if node_id is None:
                out.append(value)
                continue
            merged = dict(value)
            merged["id"] = node_id
            out.append(merged)
        return out
    return []


def sync_entities_from_zwavejs(*, zwavejs: ZwavejsGateway, now=None, per_node_limit: int = 200) -> dict[str, Any]:
    """Sync entities from Z-Wave JS into the local entity registry (best-effort)."""
    now = now or timezone.now()
    imported = 0
    updated = 0
    warnings: list[str] = []

    controller_state = zwavejs.controller_get_state(timeout_seconds=10)
    nodes_obj = None
    state_obj = None
    if isinstance(controller_state, dict):
        state_obj = controller_state.get("state") if isinstance(controller_state.get("state"), dict) else controller_state
        nodes_obj = state_obj.get("nodes") if isinstance(state_obj, dict) else None

    nodes = _extract_nodes(controller_state)
    raw_node_count = len(nodes)
    candidate_node_count = 0
    nodes_value_ids_failed = 0
    nodes_value_ids_empty = 0
    value_ids_total = 0

    # If the homeId isn't available (e.g. we connected but haven't received the version message),
    # still import with 0 so entity ids are stable within this runtime.
    home_id = zwavejs.get_home_id() or 0

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id") if isinstance(node.get("id"), int) else node.get("nodeId")
        if not isinstance(node_id, int) or node_id <= 0:
            continue

        candidate_node_count += 1

        node_name = node.get("name") if isinstance(node.get("name"), str) and node.get("name") else None
        if not node_name and isinstance(node.get("label"), str) and node.get("label"):
            node_name = node.get("label")
        if not node_name and isinstance(node.get("productLabel"), str) and node.get("productLabel"):
            node_name = node.get("productLabel")
        node_name = node_name or f"Node {node_id}"

        try:
            value_ids = zwavejs.node_get_defined_value_ids(node_id=node_id, timeout_seconds=10)
        except Exception as exc:
            nodes_value_ids_failed += 1
            if len(warnings) < 10:
                warnings.append(
                    f"Node {node_id}: failed to fetch value IDs ({exc.__class__.__name__}: {str(exc) or 'unknown error'})."
                )
            continue
        if not value_ids:
            nodes_value_ids_empty += 1
        value_ids_total += len(value_ids)

        count = 0
        for value_id in value_ids:
            if not isinstance(value_id, dict):
                continue
            command_class = value_id.get("commandClass")
            prop = value_id.get("property")
            if not isinstance(command_class, int) or prop is None:
                continue

            count += 1
            if per_node_limit and count > per_node_limit:
                break

            try:
                metadata = zwavejs.node_get_value_metadata(node_id=node_id, value_id=value_id, timeout_seconds=10)
            except Exception:
                metadata = {}

            try:
                value = zwavejs.node_get_value(node_id=node_id, value_id=value_id, timeout_seconds=10)
            except Exception:
                value = None

            entity_id = build_zwavejs_entity_id(home_id=home_id, node_id=node_id, value_id=value_id)
            domain = infer_entity_domain(value=value)
            label = metadata.get("label") if isinstance(metadata.get("label"), str) else None
            name = f"{node_name} • {label}" if label else f"{node_name} • {entity_id}"

            defaults = {
                "domain": domain,
                "name": name,
                "device_class": None,
                "last_state": normalize_entity_state(value=value),
                "last_changed": now,
                "last_seen": now,
                "attributes": {
                    "zwavejs": {
                        "home_id": home_id,
                        "node_id": node_id,
                        "node_name": node_name,
                        "value_id": value_id,
                        "metadata": metadata,
                    }
                },
                "source": "zwavejs",
            }

            _, created = Entity.objects.update_or_create(entity_id=entity_id, defaults=defaults)
            imported += 1 if created else 0
            updated += 0 if created else 1

    if candidate_node_count == 0:
        keys = sorted([str(k) for k in controller_state.keys()]) if isinstance(controller_state, dict) else []
        state_keys = sorted([str(k) for k in state_obj.keys()]) if isinstance(state_obj, dict) else []
        warnings.append(
            "No Z-Wave nodes found in controller state."
            + (f" controller_state_keys={keys}." if keys else "")
            + (f" state_keys={state_keys}." if state_keys else "")
            + (f" nodes_type={type(nodes_obj).__name__}." if nodes_obj is not None else "")
        )
    elif value_ids_total == 0 and nodes_value_ids_failed == 0:
        warnings.append("No value IDs found on any node (nodes may still be interviewing or unsupported by the server API).")

    return {
        "imported": imported,
        "updated": updated,
        "timestamp": now,
        "warnings": warnings,
        "raw_node_count": raw_node_count,
        "candidate_node_count": candidate_node_count,
        "nodes_value_ids_failed": nodes_value_ids_failed,
        "nodes_value_ids_empty": nodes_value_ids_empty,
        "value_ids_total": value_ids_total,
    }
