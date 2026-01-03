from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from typing import Any, Callable

from django.db import transaction
from django.utils import timezone

from .models import RuleRuntimeState
from .rules.action_executor import execute_actions
from .rules.audit_log import log_rule_action
from .rules.conditions import (
    eval_condition_explain_with_context,
    eval_condition_with_context,
    extract_for,
)
from .rules.repositories import RuleEngineRepositories, default_rule_engine_repositories
from .rules.runtime_state import cooldown_active

from config.domain_exceptions import DomainError

class RuleEngineError(DomainError):
    pass


@dataclass(frozen=True)
class RuleRunResult:
    evaluated: int
    fired: int
    scheduled: int
    skipped_cooldown: int
    errors: int

    def as_dict(self) -> dict[str, int]:
        """Serialize run summary counters to a JSON-friendly dict."""
        return {
            "evaluated": self.evaluated,
            "fired": self.fired,
            "scheduled": self.scheduled,
            "skipped_cooldown": self.skipped_cooldown,
            "errors": self.errors,
        }


@transaction.atomic
def run_rules(
    *,
    now=None,
    actor_user=None,
    repos: RuleEngineRepositories | None = None,
    execute_actions_func: Callable[..., dict[str, Any]] = execute_actions,
    log_action_func: Callable[..., None] = log_rule_action,
) -> RuleRunResult:
    """Evaluate enabled rules and execute/schedule actions, returning summary counters."""
    repos = repos or default_rule_engine_repositories()
    now = now or timezone.now()
    rules = repos.list_enabled_rules()
    entity_state = repos.entity_state_map()

    fired = 0
    scheduled = 0
    skipped_cooldown = 0
    errors = 0

    due_runtimes = repos.due_runtimes(now)

    for runtime in due_runtimes:
        rule = runtime.rule
        seconds, child = extract_for((rule.definition or {}).get("when") if isinstance(rule.definition, dict) else None)
        if not seconds:
            runtime.scheduled_for = None
            runtime.became_true_at = None
            runtime.save(update_fields=["scheduled_for", "became_true_at", "updated_at"])
            continue

        matched = eval_condition_with_context(child, entity_state=entity_state, now=now, repos=repos)
        if not matched:
            runtime.scheduled_for = None
            runtime.became_true_at = None
            runtime.save(update_fields=["scheduled_for", "became_true_at", "updated_at"])
            continue

        if cooldown_active(rule=rule, runtime=runtime, now=now):
            skipped_cooldown += 1
            runtime.scheduled_for = None
            runtime.save(update_fields=["scheduled_for", "updated_at"])
            continue

        try:
            then = (rule.definition or {}).get("then") if isinstance(rule.definition, dict) else []
            actions = then if isinstance(then, list) else []
            result = execute_actions_func(rule=rule, actions=actions, now=now, actor_user=actor_user)
            log_action_func(
                rule=rule,
                fired_at=now,
                kind=rule.kind,
                actions=actions,
                result=result,
                trace={"source": "timer"},
            )
            runtime.last_fired_at = now
            runtime.scheduled_for = None
            runtime.save(update_fields=["last_fired_at", "scheduled_for", "updated_at"])
            fired += 1
        except Exception as exc:  # pragma: no cover - defensive
            errors += 1
            log_action_func(
                rule=rule,
                fired_at=now,
                kind=rule.kind,
                actions=[],
                result={},
                trace={"source": "timer"},
                error=str(exc),
            )

    for rule in rules:
        definition = rule.definition or {}
        when_node = definition.get("when") if isinstance(definition, dict) else None
        seconds, child = extract_for(when_node)

        if seconds:
            runtime = repos.ensure_runtime(rule)
            matched = eval_condition_with_context(child, entity_state=entity_state, now=now, repos=repos)
            if not matched:
                if runtime.became_true_at or runtime.scheduled_for:
                    runtime.became_true_at = None
                    runtime.scheduled_for = None
                    runtime.save(update_fields=["became_true_at", "scheduled_for", "updated_at"])
                continue

            if runtime.became_true_at is None or runtime.scheduled_for is None:
                runtime.became_true_at = now
                runtime.scheduled_for = now + timedelta(seconds=seconds)
                runtime.save(update_fields=["became_true_at", "scheduled_for", "updated_at"])
                scheduled += 1
            continue

        matched = eval_condition_with_context(when_node, entity_state=entity_state, now=now, repos=repos)
        if not matched:
            continue

        runtime = repos.ensure_runtime(rule)
        if cooldown_active(rule=rule, runtime=runtime, now=now):
            skipped_cooldown += 1
            continue

        then = definition.get("then") if isinstance(definition, dict) else []
        actions = then if isinstance(then, list) else []
        try:
            result = execute_actions_func(rule=rule, actions=actions, now=now, actor_user=actor_user)
            log_action_func(
                rule=rule,
                fired_at=now,
                kind=rule.kind,
                actions=actions,
                result=result,
                trace={"source": "immediate"},
            )
            runtime.last_fired_at = now
            runtime.save(update_fields=["last_fired_at", "updated_at"])
            fired += 1
        except Exception as exc:  # pragma: no cover - defensive
            errors += 1
            log_action_func(
                rule=rule,
                fired_at=now,
                kind=rule.kind,
                actions=actions,
                result={},
                trace={"source": "immediate"},
                error=str(exc),
            )

    return RuleRunResult(
        evaluated=len(rules),
        fired=fired,
        scheduled=scheduled,
        skipped_cooldown=skipped_cooldown,
        errors=errors,
    )


def simulate_rules(
    *,
    entity_states: dict[str, str],
    now=None,
    assume_for_seconds: int | None = None,
    repos: RuleEngineRepositories | None = None,
    alarm_state: str | None = None,
) -> dict[str, Any]:
    """
    Dry-run: evaluates rules against provided entity_states and returns what would happen.
    No actions are executed.
    """
    now = now or timezone.now()
    repos = repos or default_rule_engine_repositories()
    if alarm_state is not None:
        original = repos

        def _get_alarm_state_override() -> str | None:
            """Override the alarm state for repository-backed conditions during simulation."""
            return alarm_state

        repos = RuleEngineRepositories(
            list_enabled_rules=original.list_enabled_rules,
            entity_state_map=original.entity_state_map,
            due_runtimes=original.due_runtimes,
            ensure_runtime=original.ensure_runtime,
            frigate_is_available=original.frigate_is_available,
            list_frigate_detections=original.list_frigate_detections,
            get_alarm_state=_get_alarm_state_override,
        )
    assume_for_seconds = assume_for_seconds if isinstance(assume_for_seconds, int) else None
    if assume_for_seconds is not None and assume_for_seconds < 0:
        assume_for_seconds = 0

    rules = repos.list_enabled_rules()
    db_entities = repos.entity_state_map()
    merged_state: dict[str, str | None] = {**db_entities, **entity_states}

    matched: list[dict[str, Any]] = []
    not_matched: list[dict[str, Any]] = []

    for rule in rules:
        definition = rule.definition or {}
        when_node = definition.get("when") if isinstance(definition, dict) else None
        seconds, child = extract_for(when_node)

        if seconds:
            ok_child, trace = eval_condition_explain_with_context(child, entity_state=merged_state, now=now, repos=repos)
            if not ok_child:
                not_matched.append(
                    {
                        "id": rule.id,
                        "name": rule.name,
                        "kind": rule.kind,
                        "priority": rule.priority,
                        "matched": False,
                        "for": {"seconds": seconds, "status": "not_true"},
                        "trace": trace,
                    }
                )
                continue
            satisfied = assume_for_seconds is not None and assume_for_seconds >= seconds
            if not satisfied:
                matched.append(
                    {
                        "id": rule.id,
                        "name": rule.name,
                        "kind": rule.kind,
                        "priority": rule.priority,
                        "matched": False,
                        "for": {"seconds": seconds, "status": "would_schedule"},
                        "trace": trace,
                        "actions": definition.get("then") if isinstance(definition.get("then"), list) else [],
                    }
                )
                continue
            matched.append(
                {
                    "id": rule.id,
                    "name": rule.name,
                    "kind": rule.kind,
                    "priority": rule.priority,
                    "matched": True,
                    "for": {"seconds": seconds, "status": "assumed_satisfied", "assumed_for_seconds": assume_for_seconds},
                    "trace": trace,
                    "actions": definition.get("then") if isinstance(definition.get("then"), list) else [],
                }
            )
            continue

        ok, trace = eval_condition_explain_with_context(when_node, entity_state=merged_state, now=now, repos=repos)
        payload = {
            "id": rule.id,
            "name": rule.name,
            "kind": rule.kind,
            "priority": rule.priority,
            "matched": ok,
            "trace": trace,
            "actions": definition.get("then") if isinstance(definition.get("then"), list) else [],
        }
        if ok:
            matched.append(payload)
        else:
            not_matched.append(payload)

    return {
        "timestamp": now.isoformat(),
        "summary": {
            "evaluated": len(rules),
            "matched": sum(1 for r in matched if r.get("matched") is True),
            "would_schedule": sum(1 for r in matched if r.get("for", {}).get("status") == "would_schedule"),
        },
        "matched_rules": matched,
        "non_matching_rules": not_matched,
    }
