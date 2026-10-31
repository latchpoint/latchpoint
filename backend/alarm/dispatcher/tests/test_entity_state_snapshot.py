"""Tests for dispatcher entity-state snapshot optimization (ADR 0061)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from django.test import TransactionTestCase

from alarm.dispatcher.config import DispatcherConfig
from alarm.dispatcher.dispatcher import EntityChangeBatch, RuleDispatcher


# TransactionTestCase: `_dispatch_batch` calls `close_old_connections()`, which closes the
# connection inside TestCase's transaction on Postgres (a no-op on in-memory SQLite).
class TestEntityStateSnapshot(TransactionTestCase):
    def test_dispatcher_does_not_call_full_entity_snapshot(self):
        dispatcher = RuleDispatcher(config=DispatcherConfig())

        rule = MagicMock()
        rule.id = 1
        rule.kind = "trigger"
        rule.definition = {
            "when": {
                "op": "entity_state",
                "entity_id": "binary_sensor.front_door",
                "equals": "on",
            },
            "then": [{"type": "alarm_trigger"}],
        }

        batch = EntityChangeBatch(
            source="test",
            entity_ids={"binary_sensor.front_door"},
            changed_at=None,
            batch_id="b1",
        )

        dispatcher._resolve_impacted_rules = lambda _ids: [rule]  # type: ignore[method-assign]

        # If the old full snapshot path is called, fail the test.
        dispatcher._get_entity_state_map = lambda: (_ for _ in ()).throw(
            AssertionError("should not call full snapshot")
        )  # type: ignore[method-assign]

        runtime = MagicMock()
        runtime.error_suspended = False
        runtime.next_allowed_at = None
        runtime.consecutive_failures = 0

        last_changed = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

        with (
            patch("alarm.dispatcher.dispatcher.cache.add", return_value=True),
            patch("alarm.dispatcher.dispatcher.cache.delete"),
            patch(
                "alarm.models.RuleRuntimeState.objects.get_or_create",
                return_value=(runtime, True),
            ),
            patch(
                "alarm.dispatcher.dispatcher.is_rule_allowed",
                return_value=(True, "allowed"),
            ),
            patch(
                "alarm.rules_engine.run_rules",
                return_value=MagicMock(evaluated=1, fired=0, scheduled=0, errors=0),
            ) as mock_run_rules,
            patch("alarm.models.RuleEntityRef.objects.filter") as mock_refs_filter,
            patch("alarm.models.Entity.objects.filter") as mock_entity_filter,
        ):
            # No refs returned; entity IDs come from rule.definition extraction.
            mock_refs_filter.return_value.values_list.return_value = []
            # Same row shape `_get_entity_maps_for_rules` selects: (entity_id, last_state, last_changed).
            mock_entity_filter.return_value.values_list.return_value = [
                ("binary_sensor.front_door", "on", last_changed)
            ]
            dispatcher._dispatch_batch(batch)

        mock_entity_filter.assert_called()
        args, kwargs = mock_entity_filter.call_args
        self.assertIn("entity_id__in", kwargs)
        self.assertEqual(set(kwargs["entity_id__in"]), {"binary_sensor.front_door"})

        # The rule ran against the scoped snapshot built from those rows.
        mock_run_rules.assert_called_once()
        repos = mock_run_rules.call_args.kwargs["repos"]
        self.assertEqual(repos.entity_state_map(), {"binary_sensor.front_door": "on"})
        self.assertEqual(repos.entity_last_changed_map(), {"binary_sensor.front_door": last_changed})
        self.assertEqual(dispatcher._stats.entity_state_snapshot_size_last, 1)
        self.assertEqual(dispatcher._stats.rules_evaluated, 1)
        self.assertEqual(dispatcher._stats.rules_errors, 0)
