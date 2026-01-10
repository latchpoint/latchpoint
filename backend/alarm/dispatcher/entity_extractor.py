"""Extract entity IDs from rule definitions."""

from __future__ import annotations

from typing import Any


SYSTEM_ALARM_STATE_ENTITY_ID = "__system.alarm_state"


def frigate_person_detected_entity_id(camera: str) -> str:
    camera = (camera or "").strip()
    return f"__frigate.person_detected:{camera}" if camera else "__frigate.person_detected"


def extract_entity_ids_from_definition(definition: Any) -> set[str]:
    """
    Walk the 'when' condition tree and extract all entity_id references.

    Note: this includes synthetic dependency IDs for non-entity operators so the
    dispatcher can route evaluations without falling back to "evaluate all rules".

    Handles operators: entity_state, all, any, not, for

    Args:
        definition: Rule definition dict with "when" and "then" keys

    Returns:
        Set of entity_id strings referenced in the condition tree
    """
    entity_ids: set[str] = set()

    if not isinstance(definition, dict):
        return entity_ids

    when_node = definition.get("when")
    if when_node:
        _extract_from_node(when_node, entity_ids)

    return entity_ids


def extract_entity_sources_from_definition(definition: Any) -> dict[str, str]:
    """
    Walk the 'when' condition tree and extract entity_id -> source hints.

    The rule DSL may optionally include a `source` field on `entity_state` nodes.
    This is primarily a UI hint (preserve the selected dropdown), but it is also
    used by the backend to backfill `Entity.source` when an entity row is created
    via rule refs before an integration sync has populated it.

    Notes:
    - Only returns concrete integration sources (e.g. "home_assistant", "zwavejs",
      "zigbee2mqtt"). The special UI value "all" is ignored.
    - If the same entity_id appears multiple times, the first concrete source
      wins (subsequent values are ignored).
    """
    entity_sources: dict[str, str] = {}

    if not isinstance(definition, dict):
        return entity_sources

    when_node = definition.get("when")
    if when_node:
        _extract_sources_from_node(when_node, entity_sources)

    return entity_sources


def _extract_from_node(node: Any, entity_ids: set[str]) -> None:
    """
    Recursively extract entity_ids from a condition node.

    Args:
        node: Condition node (dict with "op" key)
        entity_ids: Set to add discovered entity_ids to (mutated)
    """
    if not isinstance(node, dict):
        return

    op = node.get("op")

    if op == "entity_state":
        # Direct entity reference
        entity_id = node.get("entity_id")
        if isinstance(entity_id, str) and entity_id.strip():
            entity_ids.add(entity_id.strip())

    elif op == "alarm_state_in":
        # Synthetic dependency to route alarm-state-based rules.
        entity_ids.add(SYSTEM_ALARM_STATE_ENTITY_ID)

    elif op == "frigate_person_detected":
        # Synthetic per-camera dependencies to route Frigate-triggered rules.
        cameras = node.get("cameras", [])
        if isinstance(cameras, list) and cameras:
            for camera in cameras:
                if isinstance(camera, str) and camera.strip():
                    entity_ids.add(frigate_person_detected_entity_id(camera))
        else:
            entity_ids.add(frigate_person_detected_entity_id(""))

    elif op in ("all", "any"):
        # Logical operators with children array
        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                _extract_from_node(child, entity_ids)

    elif op == "not":
        # Logical NOT with single child
        child = node.get("child")
        if child:
            _extract_from_node(child, entity_ids)

    elif op == "for":
        # Delay wrapper with single child
        child = node.get("child")
        if child:
            _extract_from_node(child, entity_ids)

    # Other operators don't contribute to dispatcher dependencies.


def _extract_sources_from_node(node: Any, entity_sources: dict[str, str]) -> None:
    """Recursively extract entity source hints from a condition node."""
    if not isinstance(node, dict):
        return

    op = node.get("op")

    if op == "entity_state":
        entity_id = node.get("entity_id")
        raw_source = node.get("source")
        if not isinstance(entity_id, str) or not entity_id.strip():
            return
        if not isinstance(raw_source, str) or not raw_source.strip():
            return
        source = raw_source.strip()
        if source == "all":
            return
        # Only record the first concrete source hint for a given entity_id.
        entity_sources.setdefault(entity_id.strip(), source)
        return

    if op in ("all", "any"):
        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                _extract_sources_from_node(child, entity_sources)
        return

    if op == "not":
        child = node.get("child")
        if child:
            _extract_sources_from_node(child, entity_sources)
        return

    if op == "for":
        child = node.get("child")
        if child:
            _extract_sources_from_node(child, entity_sources)
        return


def validate_entity_ids_exist(entity_ids: set[str]) -> tuple[set[str], set[str]]:
    """
    Validate that entity IDs exist in the database.

    Args:
        entity_ids: Set of entity_id strings to validate

    Returns:
        Tuple of (existing_ids, missing_ids)
    """
    if not entity_ids:
        return set(), set()

    from alarm.models import Entity

    existing = set(
        Entity.objects.filter(entity_id__in=entity_ids).values_list("entity_id", flat=True)
    )
    missing = entity_ids - existing

    return existing, missing
