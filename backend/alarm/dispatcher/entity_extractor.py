"""Extract entity IDs from rule definitions."""

from __future__ import annotations

from typing import Any


def extract_entity_ids_from_definition(definition: Any) -> set[str]:
    """
    Walk the 'when' condition tree and extract all entity_id references.

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

    # Note: frigate_detection, alarm_state_in, etc. don't reference entities directly
    # They're handled differently (frigate via synthetic source, alarm via global state)


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
