from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from alarm import rules_engine
from alarm.dispatcher import invalidate_entity_rule_cache
from alarm.dispatcher.entity_extractor import (
    extract_entity_ids_from_definition,
    extract_entity_sources_from_definition,
)
from alarm.models import Rule
from alarm.use_cases.rule_entity_refs import sync_rule_entity_refs
from config.domain_exceptions import ValidationError


@dataclass(frozen=True)
class RuleSimulateInput:
    entity_states: dict[str, str]
    assume_for_seconds: int | None
    alarm_state: str | None


class RuleSimulateInputError(ValidationError):
    pass


def list_rules(*, kind: str | None, enabled: str | None):
    """Return a queryset of rules, optionally filtered by kind and enabled flag."""
    queryset = Rule.objects.all().prefetch_related("entity_refs__entity")
    if kind:
        queryset = queryset.filter(kind=kind)
    if enabled in {"true", "false"}:
        queryset = queryset.filter(enabled=(enabled == "true"))
    return queryset.order_by("-priority", "id")


def parse_simulate_input(payload) -> RuleSimulateInput:
    """Parse and validate rule simulation input payload."""
    entity_states = payload.get("entity_states") if isinstance(payload, dict) else None
    if entity_states is None:
        entity_states = {}
    if not isinstance(entity_states, dict):
        raise RuleSimulateInputError("entity_states must be an object.")

    cleaned: dict[str, str] = {}
    for key, value in entity_states.items():
        if not isinstance(key, str):
            continue
        if not isinstance(value, str):
            continue
        entity_id = key.strip()
        if not entity_id:
            continue
        cleaned[entity_id] = value

    assume_for_seconds = payload.get("assume_for_seconds") if isinstance(payload, dict) else None
    if assume_for_seconds is not None and not isinstance(assume_for_seconds, int):
        raise RuleSimulateInputError("assume_for_seconds must be an integer.")

    alarm_state = payload.get("alarm_state") if isinstance(payload, dict) else None
    if alarm_state is not None and not isinstance(alarm_state, str):
        raise RuleSimulateInputError("alarm_state must be a string.")
    alarm_state = (alarm_state or "").strip() or None

    return RuleSimulateInput(entity_states=cleaned, assume_for_seconds=assume_for_seconds, alarm_state=alarm_state)


def run_rules(*, actor_user):
    """Run all enabled rules immediately."""
    return rules_engine.run_rules(actor_user=actor_user)


def simulate_rules(*, input_data: RuleSimulateInput):
    """Simulate rule evaluation using injected entity states and optional context."""
    return rules_engine.simulate_rules(
        entity_states=input_data.entity_states,
        assume_for_seconds=input_data.assume_for_seconds,
        alarm_state=input_data.alarm_state,
    )


_ACTION_TYPE_TO_KIND: dict[str, str] = {
    "alarm_trigger": "trigger",
    "alarm_disarm": "disarm",
    "alarm_arm": "arm",
}


def derive_kind_from_actions(definition: Any) -> str:
    """Derive rule kind from the first action in the then clause."""
    then_actions = definition.get("then", []) if isinstance(definition, dict) else []
    if not then_actions:
        return "trigger"  # Default

    first_action = then_actions[0] if isinstance(then_actions, list) else {}
    action_type = first_action.get("type", "") if isinstance(first_action, dict) else ""

    return _ACTION_TYPE_TO_KIND.get(action_type, "trigger")


def create_rule(*, validated_data: dict, entity_ids: list[str] | None) -> Rule:
    """Orchestrate rule creation: derive kind, extract entities, persist, invalidate cache."""
    data = {**validated_data}

    definition = data.get("definition", {})
    if "kind" not in data or not data.get("kind"):
        data["kind"] = derive_kind_from_actions(definition)

    entity_sources = extract_entity_sources_from_definition(definition)
    extracted_entity_ids = set(extract_entity_ids_from_definition(definition))

    if entity_ids is None:
        entity_ids = sorted(extracted_entity_ids)
    else:
        entity_ids = sorted(set(entity_ids) | extracted_entity_ids)

    with transaction.atomic():
        rule = Rule.objects.create(**data)
        sync_rule_entity_refs(rule=rule, entity_ids=entity_ids, entity_sources=entity_sources)
        transaction.on_commit(invalidate_entity_rule_cache)

    return rule


def update_rule(*, rule: Rule, validated_data: dict, entity_ids: list[str] | None) -> Rule:
    """Orchestrate rule update: derive kind, extract entities, persist, invalidate cache."""
    data = {**validated_data}

    definition = data.get("definition", rule.definition)
    if "kind" not in data or not data.get("kind"):
        data["kind"] = derive_kind_from_actions(definition)

    # Manual update — Rule has no M2M fields, so setattr+save is equivalent to serializer.update()
    for attr, value in data.items():
        setattr(rule, attr, value)

    if entity_ids is None and "definition" in data:
        extracted_entity_ids = set(extract_entity_ids_from_definition(definition))
        entity_ids = sorted(extracted_entity_ids)
    elif entity_ids is not None:
        extracted_entity_ids = set(extract_entity_ids_from_definition(definition))
        entity_ids = sorted(set(entity_ids) | extracted_entity_ids)

    with transaction.atomic():
        rule.save()
        if entity_ids is not None:
            entity_sources = extract_entity_sources_from_definition(definition)
            sync_rule_entity_refs(rule=rule, entity_ids=entity_ids, entity_sources=entity_sources)
        transaction.on_commit(invalidate_entity_rule_cache)

    return rule
