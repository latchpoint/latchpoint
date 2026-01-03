from __future__ import annotations

from dataclasses import dataclass

from alarm import rules_engine
from alarm.models import Rule
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
