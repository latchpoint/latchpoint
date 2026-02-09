"""Unit tests for individual action handler modules.

Each handler is tested in isolation via its ``execute(action, ctx)`` function
with a mock ``ActionContext`` — no integration through ``execute_actions()``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

from django.test import TestCase

from alarm.models import AlarmSettingsProfile, Rule
from alarm.rules.action_handlers import ActionContext
from alarm.rules.action_handlers.alarm_arm import execute as alarm_arm_execute
from alarm.rules.action_handlers.alarm_disarm import execute as alarm_disarm_execute
from alarm.rules.action_handlers.alarm_trigger import execute as alarm_trigger_execute
from alarm.rules.action_handlers.ha_call_service import execute as ha_call_service_execute
from alarm.rules.action_handlers.send_notification import execute as send_notification_execute
from alarm.rules.action_handlers.zigbee2mqtt_light import execute as zigbee2mqtt_light_execute
from alarm.rules.action_handlers.zigbee2mqtt_set_value import execute as zigbee2mqtt_set_value_execute
from alarm.rules.action_handlers.zigbee2mqtt_switch import execute as zigbee2mqtt_switch_execute
from alarm.rules.action_handlers.zwavejs_set_value import execute as zwavejs_set_value_execute
from alarm.tests.settings_test_utils import set_profile_settings


# ── helpers ──────────────────────────────────────────────────────────────────


class _FakeAlarmServices:
    def __init__(self, *, fail: bool = False):
        self.calls: list[tuple] = []
        self._fail = fail

    def disarm(self, *, user=None, code=None, reason: str = ""):
        self.calls.append(("disarm", user, reason))
        if self._fail:
            raise RuntimeError("disarm boom")

    def arm(self, *, target_state: str, user=None, code=None, reason: str = ""):
        self.calls.append(("arm", target_state, user, reason))
        if self._fail:
            raise RuntimeError("arm boom")

    def trigger(self, *, user=None, reason: str = ""):
        self.calls.append(("trigger", user, reason))
        if self._fail:
            raise RuntimeError("trigger boom")

    def get_current_snapshot(self, *, process_timers: bool):
        return None  # not used by individual handlers


class _FakeHA:
    def __init__(self, *, fail: bool = False):
        self.calls: list[tuple] = []
        self._fail = fail

    def call_service(self, *, domain, service, target=None, service_data=None, timeout_seconds: float = 5.0):
        self.calls.append((domain, service, target, service_data))
        if self._fail:
            raise RuntimeError("ha boom")


class _FakeZwavejs:
    def __init__(self, *, fail: bool = False):
        self.calls: list[tuple] = []
        self._fail = fail

    def apply_settings(self, *, settings_obj):
        self.calls.append(("apply_settings", settings_obj))

    def ensure_connected(self, *, timeout_seconds: float = 5.0):
        self.calls.append(("ensure_connected", timeout_seconds))

    def set_value(self, *, node_id, endpoint, command_class, property, value, property_key=None):
        self.calls.append(("set_value", node_id, endpoint, command_class, property, property_key, value))
        if self._fail:
            raise RuntimeError("zwavejs boom")


class _FakeZ2M:
    def __init__(self, *, fail: bool = False):
        self.calls: list[tuple] = []
        self._fail = fail

    def set_entity_value(self, *, entity_id, value):
        self.calls.append(("set_entity_value", entity_id, value))
        if self._fail:
            raise RuntimeError("z2m boom")


def _make_ctx(
    *,
    rule=None,
    alarm_services=None,
    ha=None,
    zwavejs=None,
    zigbee2mqtt=None,
    fail: bool = False,
) -> ActionContext:
    if rule is None:
        rule = Rule(id=99, name="TestRule", kind="trigger", enabled=True, priority=0, schema_version=1, definition={})
    return ActionContext(
        rule=rule,
        actor_user=None,
        alarm_services=alarm_services or _FakeAlarmServices(fail=fail),
        ha=ha or _FakeHA(fail=fail),
        zwavejs=zwavejs or _FakeZwavejs(fail=fail),
        zigbee2mqtt=zigbee2mqtt or _FakeZ2M(fail=fail),
    )


# ── alarm_disarm ─────────────────────────────────────────────────────────────


class AlarmDisarmHandlerTests(TestCase):
    def test_happy_path(self):
        ctx = _make_ctx()
        result, error = alarm_disarm_execute({"type": "alarm_disarm"}, ctx)
        self.assertTrue(result["ok"])
        self.assertIsNone(error)

    def test_exception_path(self):
        ctx = _make_ctx(fail=True)
        result, error = alarm_disarm_execute({"type": "alarm_disarm"}, ctx)
        self.assertFalse(result["ok"])
        self.assertIn("disarm boom", error)


# ── alarm_arm ────────────────────────────────────────────────────────────────


class AlarmArmHandlerTests(TestCase):
    def test_validation_failure_missing_mode(self):
        ctx = _make_ctx()
        result, error = alarm_arm_execute({"type": "alarm_arm"}, ctx)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_mode")
        self.assertIsNone(error)

    def test_happy_path(self):
        ctx = _make_ctx()
        result, error = alarm_arm_execute({"type": "alarm_arm", "mode": "armed_home"}, ctx)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "armed_home")
        self.assertIsNone(error)

    def test_exception_path(self):
        ctx = _make_ctx(fail=True)
        result, error = alarm_arm_execute({"type": "alarm_arm", "mode": "armed_home"}, ctx)
        self.assertFalse(result["ok"])
        self.assertIn("arm boom", error)


# ── alarm_trigger ────────────────────────────────────────────────────────────


class AlarmTriggerHandlerTests(TestCase):
    def test_happy_path(self):
        ctx = _make_ctx()
        result, error = alarm_trigger_execute({"type": "alarm_trigger"}, ctx)
        self.assertTrue(result["ok"])
        self.assertIsNone(error)

    def test_exception_path(self):
        ctx = _make_ctx(fail=True)
        result, error = alarm_trigger_execute({"type": "alarm_trigger"}, ctx)
        self.assertFalse(result["ok"])
        self.assertIn("trigger boom", error)


# ── ha_call_service ──────────────────────────────────────────────────────────


class HaCallServiceHandlerTests(TestCase):
    def test_validation_failure_missing_action(self):
        ctx = _make_ctx()
        result, error = ha_call_service_execute({"type": "ha_call_service"}, ctx)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_action_format")
        self.assertIsNone(error)

    def test_validation_failure_no_dot(self):
        ctx = _make_ctx()
        result, error = ha_call_service_execute({"type": "ha_call_service", "action": "nodot"}, ctx)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_action_format")
        self.assertIsNone(error)

    def test_happy_path(self):
        ha = _FakeHA()
        ctx = _make_ctx(ha=ha)
        result, error = ha_call_service_execute(
            {"type": "ha_call_service", "action": "light.turn_on", "target": {"entity_id": "light.kitchen"}},
            ctx,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "light.turn_on")
        self.assertIsNone(error)
        self.assertEqual(ha.calls[0][0], "light")
        self.assertEqual(ha.calls[0][1], "turn_on")

    def test_exception_path(self):
        ctx = _make_ctx(fail=True)
        result, error = ha_call_service_execute(
            {"type": "ha_call_service", "action": "light.turn_on"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertIn("ha boom", error)


# ── zwavejs_set_value ────────────────────────────────────────────────────────


class ZwavejsSetValueHandlerTests(TestCase):
    def test_validation_failure_missing_node_id(self):
        ctx = _make_ctx()
        result, error = zwavejs_set_value_execute(
            {"type": "zwavejs_set_value", "value_id": {"commandClass": 49}, "value": True},
            ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_node_id_or_value_id")
        self.assertIsNone(error)

    def test_validation_failure_invalid_value_id(self):
        ctx = _make_ctx()
        result, error = zwavejs_set_value_execute(
            {"type": "zwavejs_set_value", "node_id": 5, "value_id": {"commandClass": "bad"}, "value": True},
            ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_value_id")
        self.assertIsNone(error)

    def test_happy_path(self):
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(profile, zwavejs_connection={"enabled": True, "ws_url": "ws://localhost:3000"})
        zwave = _FakeZwavejs()
        ctx = _make_ctx(zwavejs=zwave)
        result, error = zwavejs_set_value_execute(
            {
                "type": "zwavejs_set_value",
                "node_id": 12,
                "value_id": {"commandClass": 49, "endpoint": 0, "property": "targetValue"},
                "value": True,
            },
            ctx,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["node_id"], 12)
        self.assertIsNone(error)
        self.assertEqual(zwave.calls[-1][0], "set_value")

    def test_exception_path(self):
        profile = AlarmSettingsProfile.objects.create(name="Default", is_active=True)
        set_profile_settings(profile, zwavejs_connection={"enabled": True})
        ctx = _make_ctx(fail=True)
        result, error = zwavejs_set_value_execute(
            {
                "type": "zwavejs_set_value",
                "node_id": 12,
                "value_id": {"commandClass": 49, "endpoint": 0, "property": "targetValue"},
                "value": True,
            },
            ctx,
        )
        self.assertFalse(result["ok"])
        self.assertIn("zwavejs boom", error)


# ── zigbee2mqtt_set_value ────────────────────────────────────────────────────


class Zigbee2mqttSetValueHandlerTests(TestCase):
    def test_validation_failure_missing_entity_id(self):
        ctx = _make_ctx()
        result, error = zigbee2mqtt_set_value_execute(
            {"type": "zigbee2mqtt_set_value", "value": True}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_entity_id")
        self.assertIsNone(error)

    def test_validation_failure_missing_value(self):
        ctx = _make_ctx()
        result, error = zigbee2mqtt_set_value_execute(
            {"type": "zigbee2mqtt_set_value", "entity_id": "z2m.test"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_value")
        self.assertIsNone(error)

    def test_happy_path(self):
        z2m = _FakeZ2M()
        ctx = _make_ctx(zigbee2mqtt=z2m)
        result, error = zigbee2mqtt_set_value_execute(
            {"type": "zigbee2mqtt_set_value", "entity_id": "z2m.test", "value": True}, ctx,
        )
        self.assertTrue(result["ok"])
        self.assertIsNone(error)
        self.assertEqual(z2m.calls[0], ("set_entity_value", "z2m.test", True))

    def test_exception_path(self):
        ctx = _make_ctx(fail=True)
        result, error = zigbee2mqtt_set_value_execute(
            {"type": "zigbee2mqtt_set_value", "entity_id": "z2m.test", "value": True}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertIn("z2m boom", error)


# ── zigbee2mqtt_switch ───────────────────────────────────────────────────────


class Zigbee2mqttSwitchHandlerTests(TestCase):
    def test_validation_failure_missing_entity_id(self):
        ctx = _make_ctx()
        result, error = zigbee2mqtt_switch_execute(
            {"type": "zigbee2mqtt_switch", "state": "on"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_entity_id")
        self.assertIsNone(error)

    def test_validation_failure_invalid_state(self):
        ctx = _make_ctx()
        result, error = zigbee2mqtt_switch_execute(
            {"type": "zigbee2mqtt_switch", "entity_id": "z2m.test", "state": "toggle"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_state")
        self.assertIsNone(error)

    def test_happy_path(self):
        z2m = _FakeZ2M()
        ctx = _make_ctx(zigbee2mqtt=z2m)
        result, error = zigbee2mqtt_switch_execute(
            {"type": "zigbee2mqtt_switch", "entity_id": "z2m.test", "state": "on"}, ctx,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "on")
        self.assertIsNone(error)
        self.assertEqual(z2m.calls[0], ("set_entity_value", "z2m.test", {"state": True}))

    def test_exception_path(self):
        ctx = _make_ctx(fail=True)
        result, error = zigbee2mqtt_switch_execute(
            {"type": "zigbee2mqtt_switch", "entity_id": "z2m.test", "state": "on"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertIn("z2m boom", error)


# ── zigbee2mqtt_light ────────────────────────────────────────────────────────


class Zigbee2mqttLightHandlerTests(TestCase):
    def test_validation_failure_missing_entity_id(self):
        ctx = _make_ctx()
        result, error = zigbee2mqtt_light_execute(
            {"type": "zigbee2mqtt_light", "state": "on"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_entity_id")
        self.assertIsNone(error)

    def test_validation_failure_invalid_state(self):
        ctx = _make_ctx()
        result, error = zigbee2mqtt_light_execute(
            {"type": "zigbee2mqtt_light", "entity_id": "z2m.test", "state": "toggle"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_state")
        self.assertIsNone(error)

    def test_validation_failure_invalid_brightness(self):
        ctx = _make_ctx()
        result, error = zigbee2mqtt_light_execute(
            {"type": "zigbee2mqtt_light", "entity_id": "z2m.test", "state": "on", "brightness": "high"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_brightness")
        self.assertIsNone(error)

    def test_happy_path_with_brightness(self):
        z2m = _FakeZ2M()
        ctx = _make_ctx(zigbee2mqtt=z2m)
        result, error = zigbee2mqtt_light_execute(
            {"type": "zigbee2mqtt_light", "entity_id": "z2m.test", "state": "off", "brightness": 200}, ctx,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "off")
        self.assertEqual(result["brightness"], 200)
        self.assertIsNone(error)
        self.assertEqual(z2m.calls[0], ("set_entity_value", "z2m.test", {"state": False, "brightness": 200}))

    def test_happy_path_without_brightness(self):
        z2m = _FakeZ2M()
        ctx = _make_ctx(zigbee2mqtt=z2m)
        result, error = zigbee2mqtt_light_execute(
            {"type": "zigbee2mqtt_light", "entity_id": "z2m.test", "state": "on"}, ctx,
        )
        self.assertTrue(result["ok"])
        self.assertNotIn("brightness", result)
        self.assertIsNone(error)

    def test_exception_path(self):
        ctx = _make_ctx(fail=True)
        result, error = zigbee2mqtt_light_execute(
            {"type": "zigbee2mqtt_light", "entity_id": "z2m.test", "state": "on"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertIn("z2m boom", error)


# ── send_notification ────────────────────────────────────────────────────────


class SendNotificationHandlerTests(TestCase):
    def test_validation_failure_missing_provider_id(self):
        ctx = _make_ctx()
        result, error = send_notification_execute(
            {"type": "send_notification", "message": "hi"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_provider_id")
        self.assertIsNone(error)

    def test_validation_failure_missing_message(self):
        ctx = _make_ctx()
        result, error = send_notification_execute(
            {"type": "send_notification", "provider_id": "abc"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_message")
        self.assertIsNone(error)

    @patch("alarm.rules.action_handlers.send_notification.get_notification_dispatcher")
    @patch("alarm.rules.action_handlers.send_notification.get_active_settings_profile")
    def test_happy_path(self, mock_get_profile, mock_get_dispatcher):
        mock_profile = MagicMock()
        mock_get_profile.return_value = mock_profile

        mock_delivery = MagicMock()
        mock_delivery.id = "delivery-uuid-123"
        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue.return_value = (mock_delivery, None)
        mock_get_dispatcher.return_value = mock_dispatcher

        ctx = _make_ctx()
        result, error = send_notification_execute(
            {"type": "send_notification", "provider_id": "prov-1", "message": "Alert!"}, ctx,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["delivery_id"], "delivery-uuid-123")
        self.assertTrue(result["queued"])
        self.assertIsNone(error)

    @patch("alarm.rules.action_handlers.send_notification.get_notification_dispatcher")
    @patch("alarm.rules.action_handlers.send_notification.get_active_settings_profile")
    def test_enqueue_failure(self, mock_get_profile, mock_get_dispatcher):
        mock_get_profile.return_value = MagicMock()

        mock_enqueue_result = MagicMock()
        mock_enqueue_result.message = "provider disabled"
        mock_enqueue_result.error_code = "provider_disabled"
        mock_dispatcher = MagicMock()
        mock_dispatcher.enqueue.return_value = (None, mock_enqueue_result)
        mock_get_dispatcher.return_value = mock_dispatcher

        ctx = _make_ctx()
        result, error = send_notification_execute(
            {"type": "send_notification", "provider_id": "prov-1", "message": "Alert!"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "provider disabled")
        self.assertEqual(result["error_code"], "provider_disabled")
        self.assertEqual(error, "provider disabled")

    @patch("alarm.rules.action_handlers.send_notification.get_notification_dispatcher")
    def test_exception_path(self, mock_get_dispatcher):
        mock_get_dispatcher.side_effect = RuntimeError("dispatch boom")

        ctx = _make_ctx()
        result, error = send_notification_execute(
            {"type": "send_notification", "provider_id": "prov-1", "message": "Alert!"}, ctx,
        )
        self.assertFalse(result["ok"])
        self.assertIn("dispatch boom", error)
