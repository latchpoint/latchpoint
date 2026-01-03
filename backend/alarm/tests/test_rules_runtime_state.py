from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import TestCase

from alarm.models import Rule, RuleRuntimeState
from alarm.rules.runtime_state import cooldown_active, ensure_runtime


class RuleRuntimeStateTests(TestCase):
    def test_ensure_runtime_creates_default_when_missing(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
        runtime = ensure_runtime(rule)
        self.assertEqual(runtime.rule_id, rule.id)
        self.assertEqual(runtime.node_id, "when")
        self.assertEqual(runtime.status, "pending")

    def test_cooldown_active_false_without_cooldown(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={}, cooldown_seconds=None)
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
        self.assertFalse(cooldown_active(rule=rule, runtime=None, now=now))

    def test_cooldown_active_false_without_last_fired(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={}, cooldown_seconds=60)
        runtime = RuleRuntimeState.objects.create(rule=rule, node_id="when", status="pending", last_fired_at=None)
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
        self.assertFalse(cooldown_active(rule=rule, runtime=runtime, now=now))

    def test_cooldown_active_true_when_recent(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={}, cooldown_seconds=60)
        now = datetime(2025, 1, 1, 0, 1, tzinfo=dt_timezone.utc)
        runtime = RuleRuntimeState.objects.create(rule=rule, node_id="when", status="pending", last_fired_at=now - timedelta(seconds=30))
        self.assertTrue(cooldown_active(rule=rule, runtime=runtime, now=now))

    def test_cooldown_active_false_when_elapsed(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={}, cooldown_seconds=60)
        now = datetime(2025, 1, 1, 0, 2, tzinfo=dt_timezone.utc)
        runtime = RuleRuntimeState.objects.create(rule=rule, node_id="when", status="pending", last_fired_at=now - timedelta(seconds=61))
        self.assertFalse(cooldown_active(rule=rule, runtime=runtime, now=now))

