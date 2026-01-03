from __future__ import annotations

from alarm.models import Rule, RuleRuntimeState


def cooldown_active(*, rule: Rule, runtime: RuleRuntimeState | None, now) -> bool:
    """Return True if a rule is still within its cooldown period."""
    cooldown_seconds = rule.cooldown_seconds
    if not cooldown_seconds:
        return False
    last_fired_at = runtime.last_fired_at if runtime else None
    if not last_fired_at:
        return False
    return (now - last_fired_at).total_seconds() < cooldown_seconds


def ensure_runtime(rule: Rule) -> RuleRuntimeState:
    """Ensure a runtime state row exists for a rule and return it."""
    runtime, _ = RuleRuntimeState.objects.get_or_create(
        rule=rule,
        node_id="when",
        defaults={"status": "pending"},
    )
    return runtime
