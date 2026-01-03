from __future__ import annotations

from typing import Any

from alarm.models import Rule, RuleActionLog


def log_rule_action(
    *,
    rule: Rule,
    fired_at,
    kind: str,
    actions: list[dict[str, Any]],
    result: dict[str, Any],
    trace: dict[str, Any],
    error: str = "",
) -> None:
    """Persist an action execution log row for a rule run."""
    RuleActionLog.objects.create(
        rule=rule,
        entity=None,
        fired_at=fired_at,
        kind=kind,
        actions=actions,
        result=result,
        trace=trace,
        alarm_state_before=result.get("alarm_state_before", "") if isinstance(result, dict) else "",
        alarm_state_after=result.get("alarm_state_after", "") if isinstance(result, dict) else "",
        error=error,
    )
