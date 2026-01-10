"""Tests for dispatcher event-time semantics."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import MagicMock, patch

from django.utils import timezone

from alarm.dispatcher.config import DispatcherConfig
from alarm.dispatcher.dispatcher import EntityChangeBatch, RuleDispatcher


class TestDispatcherEventTime(TestCase):
    def test_rules_engine_run_uses_batch_changed_at(self):
        """
        The dispatcher should evaluate rules using the integration event timestamp,
        not the worker wall-clock time (important for `for:` timing).
        """
        dispatcher = RuleDispatcher(config=DispatcherConfig())

        rule = MagicMock()
        rule.id = 123
        rule.kind = "trigger"

        batch_changed_at = timezone.now() - timezone.timedelta(seconds=30)
        batch = EntityChangeBatch(
            source="test",
            entity_ids={"binary_sensor.front_door"},
            changed_at=batch_changed_at,
            batch_id="b1",
        )

        # Avoid DB work by stubbing dispatcher internals.
        dispatcher._resolve_impacted_rules = lambda _ids: [rule]  # type: ignore[method-assign]
        dispatcher._get_entity_state_map = lambda: {"binary_sensor.front_door": "on"}  # type: ignore[method-assign]

        runtime = MagicMock()
        runtime.error_suspended = False
        runtime.next_allowed_at = None
        runtime.consecutive_failures = 0

        with patch("alarm.dispatcher.dispatcher.cache.add", return_value=True), patch(
            "alarm.dispatcher.dispatcher.cache.delete"
        ), patch(
            "alarm.models.RuleRuntimeState.objects.get_or_create",
            return_value=(runtime, True),
        ), patch(
            "alarm.dispatcher.dispatcher.is_rule_allowed",
            return_value=(True, "allowed"),
        ) as mock_allowed, patch(
            "alarm.rules_engine.run_rules",
            return_value=MagicMock(evaluated=1, fired=0, scheduled=0, errors=0),
        ) as mock_run:
            dispatcher._dispatch_batch(batch)

        self.assertEqual(mock_run.call_args.kwargs.get("now"), batch_changed_at)
        self.assertEqual(mock_allowed.call_args.kwargs.get("now"), batch_changed_at)
