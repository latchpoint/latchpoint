from __future__ import annotations

from dataclasses import dataclass

from django.test import TestCase
from django.utils import timezone

from alarm.models import Rule
from alarm.rules_engine import run_rules


@dataclass
class _FakeRuntime:
    rule: Rule
    last_fired_at: object | None = None
    scheduled_for: object | None = None
    became_true_at: object | None = None

    def save(self, **kwargs) -> None:  # pragma: no cover - trivial
        return


class _FakeRepos:
    def __init__(self, *, rules: list[Rule], entity_state: dict[str, str | None]):
        self._rules = rules
        self._entity_state = entity_state
        self.runtimes: dict[int, _FakeRuntime] = {}

    def list_enabled_rules(self) -> list[Rule]:
        return self._rules

    def entity_state_map(self) -> dict[str, str | None]:
        return dict(self._entity_state)

    def due_runtimes(self, now):
        return []

    def ensure_runtime(self, rule: Rule) -> _FakeRuntime:
        runtime = self.runtimes.get(rule.id)
        if runtime is None:
            runtime = _FakeRuntime(rule=rule)
            self.runtimes[rule.id] = runtime
        return runtime


class RulesEngineInjectionTests(TestCase):
    def test_run_rules_uses_injected_executor_and_logger(self):
        rule = Rule(
            id=1,
            name="Trigger when door on",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            cooldown_seconds=None,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                "then": [{"type": "alarm_trigger"}],
            },
        )
        repos = _FakeRepos(rules=[rule], entity_state={"binary_sensor.front_door": "on"})

        executed: list[dict] = []
        logged: list[dict] = []

        def _exec(**kwargs):
            executed.append(kwargs)
            return {"alarm_state_before": "armed_away", "alarm_state_after": "triggered"}

        def _log(**kwargs):
            logged.append(kwargs)

        now = timezone.now()
        result = run_rules(now=now, actor_user=None, repos=repos, execute_actions_func=_exec, log_action_func=_log)

        self.assertEqual(result.evaluated, 1)
        self.assertEqual(result.fired, 1)
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0]["rule"].id, 1)
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["rule"].id, 1)
        self.assertEqual(logged[0]["trace"]["source"], "immediate")

    def test_run_rules_schedules_for_rule_without_executing(self):
        rule = Rule(
            id=2,
            name="Trigger after 5s on",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            cooldown_seconds=None,
            definition={
                "when": {
                    "op": "for",
                    "seconds": 5,
                    "child": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                },
                "then": [{"type": "alarm_trigger"}],
            },
        )
        repos = _FakeRepos(rules=[rule], entity_state={"binary_sensor.front_door": "on"})

        executed: list[dict] = []

        def _exec(**kwargs):
            executed.append(kwargs)
            return {}

        now = timezone.now()
        result = run_rules(now=now, actor_user=None, repos=repos, execute_actions_func=_exec, log_action_func=lambda **_: None)
        self.assertEqual(result.evaluated, 1)
        self.assertEqual(result.fired, 0)
        self.assertEqual(result.scheduled, 1)
        self.assertEqual(len(executed), 0)
        runtime = repos.runtimes[2]
        self.assertIsNotNone(runtime.became_true_at)
        self.assertIsNotNone(runtime.scheduled_for)

