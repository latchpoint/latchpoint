from __future__ import annotations

from dataclasses import dataclass

from django.test import SimpleTestCase

from alarm.models import Rule
from alarm.rules_engine import simulate_rules


@dataclass(frozen=True)
class _FakeRepos:
    rules: list[Rule]
    states: dict[str, str | None]

    def list_enabled_rules(self) -> list[Rule]:
        return self.rules

    def entity_state_map(self) -> dict[str, str | None]:
        return dict(self.states)

    def due_runtimes(self, now):  # pragma: no cover - not used by simulate_rules
        return []

    def ensure_runtime(self, rule):  # pragma: no cover - not used by simulate_rules
        raise AssertionError("ensure_runtime should not be called by simulate_rules")


class RulesEngineRepositoryInjectionTests(SimpleTestCase):
    def test_simulate_uses_repo_entity_state_map(self):
        rule = Rule(
            id=1,
            name="Door on triggers",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                "then": [{"type": "alarm_trigger"}],
            },
        )
        repos = _FakeRepos(rules=[rule], states={"binary_sensor.front_door": "on"})

        result = simulate_rules(entity_states={}, repos=repos)
        self.assertEqual(result["summary"]["evaluated"], 1)
        self.assertEqual(result["summary"]["matched"], 1)

    def test_simulate_for_rule_would_schedule_without_assumption(self):
        rule = Rule(
            id=2,
            name="Door on for 5s triggers",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {
                    "op": "for",
                    "seconds": 5,
                    "child": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                },
                "then": [{"type": "alarm_trigger"}],
            },
        )
        repos = _FakeRepos(rules=[rule], states={"binary_sensor.front_door": "on"})

        result = simulate_rules(entity_states={}, repos=repos)
        self.assertEqual(result["summary"]["evaluated"], 1)
        self.assertEqual(result["summary"]["matched"], 0)
        self.assertEqual(result["summary"]["would_schedule"], 1)

    def test_simulate_for_rule_assumed_satisfied(self):
        rule = Rule(
            id=3,
            name="Door on for 5s triggers",
            kind="trigger",
            enabled=True,
            priority=1,
            schema_version=1,
            definition={
                "when": {
                    "op": "for",
                    "seconds": 5,
                    "child": {"op": "entity_state", "entity_id": "binary_sensor.front_door", "equals": "on"},
                },
                "then": [{"type": "alarm_trigger"}],
            },
        )
        repos = _FakeRepos(rules=[rule], states={"binary_sensor.front_door": "on"})

        result = simulate_rules(entity_states={}, assume_for_seconds=5, repos=repos)
        self.assertEqual(result["summary"]["evaluated"], 1)
        self.assertEqual(result["summary"]["matched"], 1)

