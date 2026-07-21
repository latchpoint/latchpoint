"""Tests for entity state sync task."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from alarm.gateways.home_assistant import (
    HomeAssistantNotConfigured,
    HomeAssistantNotReachable,
)
from alarm.models import Entity, SystemConfig
from alarm.tasks import (
    LAST_SEEN_REFRESH_SECONDS,
    _get_entity_sync_interval,
    sync_entity_states,
)


def _update_statements(ctx):
    """Return the UPDATE statements captured in a CaptureQueriesContext."""
    return [q for q in ctx.captured_queries if q["sql"].lstrip().upper().startswith("UPDATE")]


class GetEntitySyncIntervalTests(TestCase):
    def test_returns_default_when_no_config(self):
        """Returns 300 (default) when no SystemConfig exists."""
        self.assertEqual(_get_entity_sync_interval(), 300)

    def test_returns_configured_value(self):
        """Returns the configured value from SystemConfig."""
        SystemConfig.objects.create(
            key="entity_sync.interval_seconds",
            name="Entity sync interval (seconds)",
            value_type="integer",
            value=600,
        )
        self.assertEqual(_get_entity_sync_interval(), 600)

    def test_handles_invalid_value_gracefully(self):
        """Falls back to default on invalid config value."""
        SystemConfig.objects.create(
            key="entity_sync.interval_seconds",
            name="Entity sync interval (seconds)",
            value_type="integer",
            value="not-a-number",
        )
        self.assertEqual(_get_entity_sync_interval(), 300)


class SyncEntityStatesTests(TestCase):
    def setUp(self):
        self.gateway_patch = patch("alarm.gateways.home_assistant.default_home_assistant_gateway")
        self.mock_gateway = self.gateway_patch.start()

    def tearDown(self):
        self.gateway_patch.stop()

    def test_disabled_when_interval_zero(self):
        """Returns early when interval is 0."""
        SystemConfig.objects.create(
            key="entity_sync.interval_seconds",
            name="Entity sync interval (seconds)",
            value_type="integer",
            value=0,
        )

        result = sync_entity_states()

        self.assertEqual(result["disabled"], True)
        self.assertEqual(result["synced"], 0)
        self.mock_gateway.ensure_available.assert_not_called()

    def test_skips_when_ha_not_configured(self):
        """Returns skipped when Home Assistant is not configured."""
        self.mock_gateway.ensure_available.side_effect = HomeAssistantNotConfigured("Not configured")

        result = sync_entity_states()

        self.assertEqual(result["skipped"], True)
        self.assertEqual(result["synced"], 0)

    def test_skips_when_ha_not_reachable(self):
        """Returns skipped when Home Assistant is not reachable."""
        self.mock_gateway.ensure_available.side_effect = HomeAssistantNotReachable("Connection refused")

        result = sync_entity_states()

        self.assertEqual(result["skipped"], True)
        self.assertEqual(result["synced"], 0)

    def test_returns_error_on_fetch_failure(self):
        """Returns error count when fetching entities fails."""
        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.side_effect = Exception("API error")

        result = sync_entity_states()

        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["synced"], 0)

    def test_syncs_entities_without_state_change(self):
        """Updates last_seen even when state hasn't changed."""
        entity = Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door",
            source="home_assistant",
            last_state="off",
        )

        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = [{"entity_id": "binary_sensor.door", "state": "off"}]

        result = sync_entity_states()

        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["updated"], 0)

        entity.refresh_from_db()
        self.assertIsNotNone(entity.last_seen)

    def test_updates_entity_with_changed_state(self):
        """Updates last_state and last_changed when state changes."""
        entity = Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door",
            source="home_assistant",
            last_state="off",
        )

        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = [{"entity_id": "binary_sensor.door", "state": "on"}]

        result = sync_entity_states()

        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["updated"], 1)

        entity.refresh_from_db()
        self.assertEqual(entity.last_state, "on")
        self.assertIsNotNone(entity.last_changed)
        self.assertIsNotNone(entity.last_seen)

    def test_ignores_non_ha_entities(self):
        """Only syncs entities with source='home_assistant'."""
        Entity.objects.create(
            entity_id="sensor.local",
            domain="sensor",
            name="Local Sensor",
            source="local",
            last_state="on",
        )

        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = [{"entity_id": "sensor.local", "state": "off"}]

        result = sync_entity_states()

        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["updated"], 0)

    def test_skips_entities_not_in_ha(self):
        """Skips entities that exist locally but not in Home Assistant."""
        Entity.objects.create(
            entity_id="binary_sensor.deleted",
            domain="binary_sensor",
            name="Deleted Sensor",
            source="home_assistant",
            last_state="on",
        )

        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = []

        result = sync_entity_states()

        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["updated"], 0)

    def test_syncs_multiple_entities(self):
        """Syncs multiple entities in one call."""
        Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door",
            source="home_assistant",
            last_state="off",
        )
        Entity.objects.create(
            entity_id="binary_sensor.window",
            domain="binary_sensor",
            name="Window",
            source="home_assistant",
            last_state="off",
        )

        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = [
            {"entity_id": "binary_sensor.door", "state": "on"},
            {"entity_id": "binary_sensor.window", "state": "off"},
        ]

        result = sync_entity_states()

        self.assertEqual(result["synced"], 2)
        self.assertEqual(result["updated"], 1)

    @patch("alarm.websocket.broadcast_entity_sync")
    def test_broadcasts_state_changes(self, mock_broadcast):
        """Broadcasts WebSocket event when entities have state changes."""
        Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door",
            source="home_assistant",
            last_state="off",
        )

        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = [{"entity_id": "binary_sensor.door", "state": "on"}]

        sync_entity_states()

        mock_broadcast.assert_called_once()
        call_args = mock_broadcast.call_args
        entities = call_args.kwargs["entities"]
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["entity_id"], "binary_sensor.door")
        self.assertEqual(entities[0]["old_state"], "off")
        self.assertEqual(entities[0]["new_state"], "on")

    @patch("alarm.websocket.broadcast_entity_sync")
    def test_no_broadcast_when_no_changes(self, mock_broadcast):
        """Does not broadcast when no state changes detected."""
        Entity.objects.create(
            entity_id="binary_sensor.door",
            domain="binary_sensor",
            name="Door",
            source="home_assistant",
            last_state="off",
        )

        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = [{"entity_id": "binary_sensor.door", "state": "off"}]

        sync_entity_states()

        mock_broadcast.assert_not_called()

    def _make_ha_available(self, ha_entities):
        self.mock_gateway.ensure_available.return_value = MagicMock()
        self.mock_gateway.list_entities.return_value = ha_entities

    def test_ac1_fresh_unchanged_entities_no_writes_and_query_count_constant(self):
        """AC-1: N fresh unchanged entities issue zero UPDATEs; query count independent of N."""
        now = timezone.now()

        def _setup(n):
            Entity.objects.filter(source="home_assistant").delete()
            Entity.objects.bulk_create(
                [
                    Entity(
                        entity_id=f"binary_sensor.s{i}",
                        domain="binary_sensor",
                        name=f"S{i}",
                        source="home_assistant",
                        last_state="off",
                        last_seen=now,
                    )
                    for i in range(n)
                ]
            )
            self._make_ha_available([{"entity_id": f"binary_sensor.s{i}", "state": "off"} for i in range(n)])

        _setup(1)
        with CaptureQueriesContext(connection) as one:
            sync_entity_states()

        _setup(10)
        with CaptureQueriesContext(connection) as ten:
            result = sync_entity_states()

        # Nothing changed and last_seen is fresh -> no writes at all.
        self.assertEqual(_update_statements(one), [])
        self.assertEqual(_update_statements(ten), [])
        # Round-trips do not grow with entity count.
        self.assertEqual(len(one.captured_queries), len(ten.captured_queries))
        self.assertEqual(result["synced"], 10)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["last_seen_refreshed"], 0)

    def test_ac1_fresh_unchanged_pass_is_two_queries(self):
        """AC-1: a fresh-unchanged pass is a bounded constant (interval read + entity select)."""
        now = timezone.now()
        for i in range(5):
            Entity.objects.create(
                entity_id=f"binary_sensor.f{i}",
                domain="binary_sensor",
                name=f"F{i}",
                source="home_assistant",
                last_state="off",
                last_seen=now,
            )
        self._make_ha_available([{"entity_id": f"binary_sensor.f{i}", "state": "off"} for i in range(5)])

        # 1 SystemConfig read + 1 Entity select; no writes.
        with self.assertNumQueries(2):
            sync_entity_states()

    @patch("alarm.dispatcher.notify_entities_changed")
    @patch("alarm.websocket.broadcast_entity_sync")
    def test_ac2_changed_entities_persist_in_single_bulk_update(self, mock_broadcast, mock_notify):
        """AC-2: M changed rows persist via one bulk_update; query count constant in M; updated == M."""

        def _setup(m):
            Entity.objects.filter(source="home_assistant").delete()
            Entity.objects.bulk_create(
                [
                    Entity(
                        entity_id=f"binary_sensor.c{i}",
                        domain="binary_sensor",
                        name=f"C{i}",
                        source="home_assistant",
                        last_state="off",
                    )
                    for i in range(m)
                ]
            )
            self._make_ha_available([{"entity_id": f"binary_sensor.c{i}", "state": "on"} for i in range(m)])

        _setup(1)
        with CaptureQueriesContext(connection) as one:
            sync_entity_states()

        _setup(5)
        with CaptureQueriesContext(connection) as five:
            result = sync_entity_states()

        # All changed rows persist in exactly one UPDATE regardless of M.
        self.assertEqual(len(_update_statements(one)), 1)
        self.assertEqual(len(_update_statements(five)), 1)
        self.assertEqual(len(one.captured_queries), len(five.captured_queries))
        self.assertEqual(result["updated"], 5)

        for i in range(5):
            e = Entity.objects.get(entity_id=f"binary_sensor.c{i}")
            self.assertEqual(e.last_state, "on")
            self.assertIsNotNone(e.last_changed)
            self.assertIsNotNone(e.last_seen)

    def test_ac3_null_or_stale_last_seen_refreshed_via_bulk_update(self):
        """AC-3: unchanged entities with NULL or stale last_seen are refreshed via one bulk UPDATE."""
        now = timezone.now()
        stale = now - timedelta(seconds=LAST_SEEN_REFRESH_SECONDS + 60)
        Entity.objects.create(
            entity_id="binary_sensor.null",
            domain="binary_sensor",
            name="Null",
            source="home_assistant",
            last_state="off",
            last_seen=None,
        )
        Entity.objects.create(
            entity_id="binary_sensor.stale",
            domain="binary_sensor",
            name="Stale",
            source="home_assistant",
            last_state="off",
            last_seen=stale,
        )
        self._make_ha_available(
            [
                {"entity_id": "binary_sensor.null", "state": "off"},
                {"entity_id": "binary_sensor.stale", "state": "off"},
            ]
        )

        with CaptureQueriesContext(connection) as ctx:
            result = sync_entity_states()

        self.assertEqual(len(_update_statements(ctx)), 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["last_seen_refreshed"], 2)

        for eid in ("binary_sensor.null", "binary_sensor.stale"):
            e = Entity.objects.get(entity_id=eid)
            self.assertIsNotNone(e.last_seen)
            self.assertGreaterEqual(e.last_seen, now)

    def test_ac4_fresh_unchanged_last_seen_value_not_rewritten(self):
        """AC-4: an unchanged entity whose last_seen is within the threshold is left untouched."""
        fresh = timezone.now() - timedelta(seconds=10)
        entity = Entity.objects.create(
            entity_id="binary_sensor.fresh",
            domain="binary_sensor",
            name="Fresh",
            source="home_assistant",
            last_state="off",
            last_seen=fresh,
        )
        self._make_ha_available([{"entity_id": "binary_sensor.fresh", "state": "off"}])

        result = sync_entity_states()

        self.assertEqual(result["last_seen_refreshed"], 0)
        entity.refresh_from_db()
        self.assertEqual(entity.last_seen, fresh)

    def test_ac8_synced_counts_present_entities_even_with_zero_writes(self):
        """AC-8: synced counts entities present in both the registry and the HA dump with no writes."""
        now = timezone.now()
        Entity.objects.create(
            entity_id="binary_sensor.a",
            domain="binary_sensor",
            name="A",
            source="home_assistant",
            last_state="off",
            last_seen=now,
        )
        Entity.objects.create(
            entity_id="binary_sensor.b",
            domain="binary_sensor",
            name="B",
            source="home_assistant",
            last_state="on",
            last_seen=now,
        )
        # Present locally but absent from the HA dump -> must not be counted.
        Entity.objects.create(
            entity_id="binary_sensor.gone",
            domain="binary_sensor",
            name="Gone",
            source="home_assistant",
            last_state="off",
            last_seen=now,
        )
        self._make_ha_available(
            [
                {"entity_id": "binary_sensor.a", "state": "off"},
                {"entity_id": "binary_sensor.b", "state": "on"},
            ]
        )

        with CaptureQueriesContext(connection) as ctx:
            result = sync_entity_states()

        self.assertEqual(_update_statements(ctx), [])
        self.assertEqual(result["synced"], 2)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["last_seen_refreshed"], 0)
