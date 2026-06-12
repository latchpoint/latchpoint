from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from alarm.models import AlarmCodeLockout, SystemConfig
from integrations_home_assistant import mqtt_alarm_entity
from integrations_home_assistant.mqtt_alarm_entity import (
    COMMAND_TOPIC,
    HomeAssistantMqttAlarmEntitySettings,
    handle_mqtt_alarm_command,
)

_ENABLED_ENTITY = HomeAssistantMqttAlarmEntitySettings(
    enabled=True,
    entity_name="Latchpoint",
    also_rename_in_home_assistant=False,
    ha_entity_id="alarm_control_panel.latchpoint_alarm",
)


def _set_config(key: str, value: int) -> None:
    SystemConfig.objects.update_or_create(
        key=key,
        defaults={"name": key, "value_type": "integer", "value": value},
    )


def _disarm(code: str) -> str:
    return json.dumps({"action": "DISARM", "code": code})


def _errors(mock_publish_error) -> list[str]:
    return [call.kwargs.get("error", "") for call in mock_publish_error.call_args_list]


class MqttAlarmEntityLockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        _set_config("alarm_code.rate_limit_max_attempts", 0)  # isolate the lockout layer
        _set_config("alarm_code.lockout_threshold", 2)
        _set_config("alarm_code.lockout_duration_seconds", 300)

    def tearDown(self):
        cache.clear()

    def test_threshold_failures_lock_then_block(self):
        with (
            patch.object(mqtt_alarm_entity, "_get_entity_settings", return_value=_ENABLED_ENTITY),
            patch.object(mqtt_alarm_entity, "disarm") as mock_disarm,
            patch.object(mqtt_alarm_entity, "publish_error") as mock_publish_error,
        ):
            # Two wrong codes (no UserCode exists) engage the global lockout.
            handle_mqtt_alarm_command(topic=COMMAND_TOPIC, payload=_disarm("9999"))
            handle_mqtt_alarm_command(topic=COMMAND_TOPIC, payload=_disarm("9999"))

            self.assertIsNotNone(AlarmCodeLockout.objects.get(id=AlarmCodeLockout.SINGLETON_ID).locked_until)

            # Next attempt is rejected by the lockout before any validation.
            handle_mqtt_alarm_command(topic=COMMAND_TOPIC, payload=_disarm("9999"))

        mock_disarm.assert_not_called()
        self.assertTrue(any("Locked out" in err for err in _errors(mock_publish_error)))

    def test_locked_row_blocks_immediately(self):
        AlarmCodeLockout.objects.create(
            id=AlarmCodeLockout.SINGLETON_ID,
            locked_until=timezone.now() + timedelta(seconds=300),
        )
        with (
            patch.object(mqtt_alarm_entity, "_get_entity_settings", return_value=_ENABLED_ENTITY),
            patch.object(mqtt_alarm_entity, "disarm") as mock_disarm,
            patch.object(mqtt_alarm_entity, "publish_error") as mock_publish_error,
        ):
            handle_mqtt_alarm_command(topic=COMMAND_TOPIC, payload=_disarm("1234"))

        mock_disarm.assert_not_called()
        self.assertTrue(any("Locked out" in err for err in _errors(mock_publish_error)))
