from __future__ import annotations

import json
import os
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from alarm.dispatcher.dispatcher import get_dispatcher
from alarm.models import AlarmSettingsEntry, Entity
from alarm.tests.settings_test_utils import reset_cached_settings_snapshots
from alarm.use_cases.settings_profile import ensure_active_settings_profile
from integrations_zigbee2mqtt.runtime import (
    _CACHE_KEY_FRIENDLY_TO_IEEE,
    _entity_ids_cache_key,
    _handle_z2m_message,
    get_settings,
)


@patch.dict(os.environ, {"ZIGBEE2MQTT_ENABLED": "true", "ZIGBEE2MQTT_BASE_TOPIC": "zigbee2mqtt"})
class Zigbee2mqttRuntimeIngestTests(TestCase):
    # These tests write the settings row directly, which does not fire
    # `settings_profile_changed`, so `get_settings()` would otherwise serve a snapshot
    # warmed by an earlier test (ADR-0103).
    def setUp(self) -> None:
        reset_cached_settings_snapshots()
        # `_handle_z2m_message` notifies the rule dispatcher, and RuleDispatcher's
        # constructor reads the `dispatcher` SystemConfig row. Build the module-level
        # singleton up front so that one-time query cannot land inside the
        # assertNumQueries blocks below — without this these tests pass only when some
        # earlier test in the same process happened to construct it first, and they fail
        # when this module is run on its own. Construction starts no threads (the worker
        # pool is created lazily).
        get_dispatcher()

    def tearDown(self) -> None:
        reset_cached_settings_snapshots()

    def test_ingest_updates_only_known_entity_ids(self):
        profile = ensure_active_settings_profile()
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="zigbee2mqtt",
            defaults={"value_type": "json", "value": {"enabled": True, "base_topic": "zigbee2mqtt"}},
        )

        ieee = "0x00124b0018e2abcd"
        friendly = "front_door"
        entity_id = f"z2m_sensor.{ieee}_battery"
        Entity.objects.create(
            entity_id=entity_id,
            domain="sensor",
            name="Battery",
            source="zigbee2mqtt",
            attributes={"zigbee2mqtt": {"ieee_address": ieee, "friendly_name": friendly}},
        )

        cache.set(_CACHE_KEY_FRIENDLY_TO_IEEE, {friendly: ieee}, timeout=None)
        cache.set(_entity_ids_cache_key(ieee=ieee), [entity_id], timeout=None)

        settings = get_settings()
        with self.assertNumQueries(1):
            _handle_z2m_message(settings=settings, topic=f"zigbee2mqtt/{friendly}", payload=json.dumps({"battery": 90}))

        updated = Entity.objects.get(entity_id=entity_id)
        self.assertEqual(updated.last_state, "90")
        self.assertIsNotNone(updated.last_seen)

    def test_ingest_skips_unknown_keys_without_db_writes(self):
        profile = ensure_active_settings_profile()
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="zigbee2mqtt",
            defaults={"value_type": "json", "value": {"enabled": True, "base_topic": "zigbee2mqtt"}},
        )

        ieee = "0x00124b0018e2abcd"
        friendly = "front_door"
        entity_id = f"z2m_sensor.{ieee}_battery"
        Entity.objects.create(
            entity_id=entity_id,
            domain="sensor",
            name="Battery",
            source="zigbee2mqtt",
            attributes={"zigbee2mqtt": {"ieee_address": ieee, "friendly_name": friendly}},
        )

        cache.set(_CACHE_KEY_FRIENDLY_TO_IEEE, {friendly: ieee}, timeout=None)
        cache.set(_entity_ids_cache_key(ieee=ieee), [entity_id], timeout=None)

        settings = get_settings()
        with self.assertNumQueries(0):
            _handle_z2m_message(settings=settings, topic=f"zigbee2mqtt/{friendly}", payload=json.dumps({"unknown": 1}))

    def _contact_sensor(self, *, last_state: str | None, last_changed=None) -> str:
        profile = ensure_active_settings_profile()
        AlarmSettingsEntry.objects.update_or_create(
            profile=profile,
            key="zigbee2mqtt",
            defaults={"value_type": "json", "value": {"enabled": True, "base_topic": "zigbee2mqtt"}},
        )
        ieee = "0x00124b0018e2abcd"
        friendly = "side_fence_door"
        entity_id = f"z2m_binary_sensor.{ieee}_contact"
        Entity.objects.create(
            entity_id=entity_id,
            domain="binary_sensor",
            name="Contact",
            source="zigbee2mqtt",
            last_state=last_state,
            last_changed=last_changed,
            attributes={"zigbee2mqtt": {"ieee_address": ieee, "friendly_name": friendly}},
        )
        cache.set(_CACHE_KEY_FRIENDLY_TO_IEEE, {friendly: ieee}, timeout=None)
        cache.set(_entity_ids_cache_key(ieee=ieee), [entity_id], timeout=None)
        return entity_id

    def _ingest(self, payload: dict) -> list:
        with patch("integrations_zigbee2mqtt.runtime._notify_dispatcher") as notify:
            _handle_z2m_message(
                settings=get_settings(), topic="zigbee2mqtt/side_fence_door", payload=json.dumps(payload)
            )
        return [c.kwargs["entity_ids"] for c in notify.call_args_list]

    def test_an_unchanged_state_doesnt_count_as_a_change(self):
        # #164: the server subscribes at startup and gets each device's retained state again, and Z2M repeats
        # the full state in every report. An open door that stayed open must not look "changed since armed"
        # (ADR-0108) or reach the rules again.
        armed_at = timezone.now() - timedelta(hours=1)
        entity_id = self._contact_sensor(last_state="False", last_changed=armed_at - timedelta(minutes=5))

        notified = self._ingest({"contact": False, "battery": 90})

        self.assertEqual(notified, [])
        entity = Entity.objects.get(entity_id=entity_id)
        self.assertEqual(entity.last_state, "False")
        self.assertLess(entity.last_changed, armed_at)
        self.assertGreater(entity.last_seen, armed_at)

    def test_a_new_state_is_a_change(self):
        entity_id = self._contact_sensor(last_state="True", last_changed=timezone.now() - timedelta(hours=1))
        before = timezone.now()

        notified = self._ingest({"contact": False})

        self.assertEqual(notified, [[entity_id]])
        entity = Entity.objects.get(entity_id=entity_id)
        self.assertEqual(entity.last_state, "False")
        self.assertGreaterEqual(entity.last_changed, before)
