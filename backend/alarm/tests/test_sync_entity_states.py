"""Tests for entity state sync task."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from alarm.gateways.home_assistant import (
    HomeAssistantNotConfigured,
    HomeAssistantNotReachable,
)
from alarm.models import Entity, SystemConfig
from alarm.tasks import _get_entity_sync_interval, sync_entity_states


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
        self.gateway_patch = patch(
            "alarm.gateways.home_assistant.default_home_assistant_gateway"
        )
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
        self.mock_gateway.ensure_available.side_effect = HomeAssistantNotConfigured(
            "Not configured"
        )

        result = sync_entity_states()

        self.assertEqual(result["skipped"], True)
        self.assertEqual(result["synced"], 0)

    def test_skips_when_ha_not_reachable(self):
        """Returns skipped when Home Assistant is not reachable."""
        self.mock_gateway.ensure_available.side_effect = HomeAssistantNotReachable(
            "Connection refused"
        )

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
        self.mock_gateway.list_entities.return_value = [
            {"entity_id": "binary_sensor.door", "state": "off"}
        ]

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
        self.mock_gateway.list_entities.return_value = [
            {"entity_id": "binary_sensor.door", "state": "on"}
        ]

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
        self.mock_gateway.list_entities.return_value = [
            {"entity_id": "sensor.local", "state": "off"}
        ]

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
        self.mock_gateway.list_entities.return_value = [
            {"entity_id": "binary_sensor.door", "state": "on"}
        ]

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
        self.mock_gateway.list_entities.return_value = [
            {"entity_id": "binary_sensor.door", "state": "off"}
        ]

        sync_entity_states()

        mock_broadcast.assert_not_called()
