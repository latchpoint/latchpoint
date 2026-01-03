from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from django.test import TestCase

from alarm.models import AlarmSettingsProfile
from alarm.models import Rule
from alarm.rules.action_executor import execute_actions
from alarm.tests.settings_test_utils import set_profile_settings


class _Snapshot:
    def __init__(self, state: str):
        self.current_state = state


class _AlarmServices:
    def __init__(self):
        self.calls = []
        self._state = "disarmed"

    def get_current_snapshot(self, *, process_timers: bool):
        self.calls.append(("get_current_snapshot", process_timers))
        return _Snapshot(self._state)

    def disarm(self, *, user=None, code=None, reason: str = ""):
        self.calls.append(("disarm", user, reason))
        self._state = "disarmed"

    def arm(self, *, target_state: str, user=None, code=None, reason: str = ""):
        self.calls.append(("arm", target_state, user, reason))
        self._state = target_state

    def trigger(self, *, user=None, reason: str = ""):
        self.calls.append(("trigger", user, reason))
        self._state = "triggered"


class _HA:
    def __init__(self):
        self.calls = []

    def call_service(self, *, domain: str, service: str, target=None, service_data=None, timeout_seconds: float = 5.0) -> None:
        self.calls.append((domain, service, target, service_data, timeout_seconds))


class ActionExecutorTests(TestCase):
    def test_execute_actions_reports_invalid_and_unsupported(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
        alarm_services = _AlarmServices()
        ha = _HA()
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)

        result = execute_actions(
            rule=rule,
            actions=[None, {"type": "nope"}, {"type": "alarm_arm"}],
            now=now,
            alarm_services=alarm_services,
            ha=ha,
        )
        self.assertEqual(result["timestamp"], now.isoformat())
        self.assertEqual(result["actions"][0]["error"], "invalid_action")
        self.assertEqual(result["actions"][1]["error"], "unsupported_action")
        self.assertEqual(result["actions"][2]["error"], "missing_mode")

    def test_execute_actions_calls_alarm_and_ha(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
        alarm_services = _AlarmServices()
        ha = _HA()
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)

        result = execute_actions(
            rule=rule,
            actions=[
                {"type": "alarm_arm", "mode": "armed_home"},
                {"type": "ha_call_service", "action": "light.turn_on", "target": {"entity_id": "light.kitchen"}},
                {"type": "alarm_trigger"},
                {"type": "alarm_disarm"},
            ],
            now=now,
            alarm_services=alarm_services,
            ha=ha,
        )
        self.assertEqual(result["alarm_state_before"], "disarmed")
        self.assertEqual(result["alarm_state_after"], "disarmed")
        self.assertEqual(len(ha.calls), 1)
        self.assertEqual(ha.calls[0][0], "light")
        self.assertEqual(ha.calls[0][1], "turn_on")

    def test_execute_actions_ha_call_service_requires_valid_action_format(self):
        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
        alarm_services = _AlarmServices()
        ha = _HA()
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
        # Missing action field
        result = execute_actions(rule=rule, actions=[{"type": "ha_call_service"}], now=now, alarm_services=alarm_services, ha=ha)
        self.assertEqual(result["actions"][0]["error"], "invalid_action_format")
        # Invalid action format (no dot)
        result = execute_actions(rule=rule, actions=[{"type": "ha_call_service", "action": "nodot"}], now=now, alarm_services=alarm_services, ha=ha)
        self.assertEqual(result["actions"][0]["error"], "invalid_action_format")

    def test_execute_actions_supports_zwavejs_set_value_shape(self):
        class _Zwavejs:
            def __init__(self):
                self.calls = []

            def apply_settings(self, *, settings_obj):
                self.calls.append(("apply_settings", settings_obj))

            def ensure_connected(self, *, timeout_seconds: float = 5.0):
                self.calls.append(("ensure_connected", timeout_seconds))

            def set_value(self, *, node_id: int, endpoint: int, command_class: int, property, value, property_key=None):
                self.calls.append(("set_value", node_id, endpoint, command_class, property, property_key, value))

        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(profile, zwavejs_connection={"enabled": True, "ws_url": "ws://zwavejs.local:3000"})

        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
        alarm_services = _AlarmServices()
        zwave = _Zwavejs()
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
        result = execute_actions(
            rule=rule,
            actions=[
                {
                    "type": "zwavejs_set_value",
                    "node_id": 12,
                    "value_id": {"commandClass": 49, "endpoint": 0, "property": "targetValue"},
                    "value": True,
                }
            ],
            now=now,
            alarm_services=alarm_services,
            ha=_HA(),
            zwavejs=zwave,
        )
        self.assertEqual(result["actions"][0]["ok"], True)
        self.assertEqual(zwave.calls[-1][0], "set_value")

    def test_execute_actions_supports_zigbee2mqtt_set_value_shape(self):
        class _Z2M:
            def __init__(self):
                self.calls = []

            def set_entity_value(self, *, entity_id: str, value):
                self.calls.append(("set_entity_value", entity_id, value))

        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
        alarm_services = _AlarmServices()
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
        z2m = _Z2M()

        result = execute_actions(
            rule=rule,
            actions=[{"type": "zigbee2mqtt_set_value", "entity_id": "z2m_switch.0x00124b_state", "value": True}],
            now=now,
            alarm_services=alarm_services,
            ha=_HA(),
            zigbee2mqtt=z2m,
        )
        self.assertEqual(result["actions"][0]["ok"], True)
        self.assertEqual(z2m.calls[-1], ("set_entity_value", "z2m_switch.0x00124b_state", True))

    def test_execute_actions_supports_zigbee2mqtt_switch_and_light(self):
        class _Z2M:
            def __init__(self):
                self.calls = []

            def set_entity_value(self, *, entity_id: str, value):
                self.calls.append(("set_entity_value", entity_id, value))

        rule = Rule.objects.create(name="R", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
        alarm_services = _AlarmServices()
        now = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
        z2m = _Z2M()

        result = execute_actions(
            rule=rule,
            actions=[
                {"type": "zigbee2mqtt_switch", "entity_id": "z2m_switch.0x00124b_state", "state": "on"},
                {"type": "zigbee2mqtt_light", "entity_id": "z2m_switch.0x00124b_state", "state": "off", "brightness": 200},
            ],
            now=now,
            alarm_services=alarm_services,
            ha=_HA(),
            zigbee2mqtt=z2m,
        )
        self.assertEqual(result["actions"][0]["ok"], True)
        self.assertEqual(result["actions"][1]["ok"], True)
        self.assertEqual(z2m.calls[0], ("set_entity_value", "z2m_switch.0x00124b_state", {"state": True}))
        self.assertEqual(z2m.calls[1], ("set_entity_value", "z2m_switch.0x00124b_state", {"state": False, "brightness": 200}))
