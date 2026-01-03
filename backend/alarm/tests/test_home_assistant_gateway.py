from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_home_assistant import impl as ha_impl
from alarm.gateways.home_assistant import DefaultHomeAssistantGateway, HomeAssistantNotConfigured, HomeAssistantNotReachable


class HomeAssistantGatewayTests(SimpleTestCase):
    def setUp(self):
        self.gateway = DefaultHomeAssistantGateway()

    @patch("alarm.gateways.home_assistant.ha_impl.ensure_available")
    def test_ensure_available_maps_not_configured(self, mock_ensure_available):
        mock_ensure_available.side_effect = ha_impl.HomeAssistantNotConfigured("missing config")
        with self.assertRaises(HomeAssistantNotConfigured) as ctx:
            self.gateway.ensure_available()
        self.assertIn("missing config", str(ctx.exception))

    @patch("alarm.gateways.home_assistant.ha_impl.ensure_available")
    def test_ensure_available_maps_not_reachable(self, mock_ensure_available):
        mock_ensure_available.side_effect = ha_impl.HomeAssistantNotReachable("boom")
        with self.assertRaises(HomeAssistantNotReachable) as ctx:
            self.gateway.ensure_available()
        self.assertEqual(getattr(ctx.exception, "error", None), "boom")

    @patch("alarm.gateways.home_assistant.ha_impl.call_service")
    def test_call_service_delegates(self, mock_call_service):
        self.gateway.call_service(
            domain="alarm_control_panel",
            service="alarm_arm_home",
            target={"entity_id": "alarm_control_panel.home"},
            service_data={"code": "1234"},
            timeout_seconds=1.5,
        )
        self.assertTrue(mock_call_service.called)
        args, kwargs = mock_call_service.call_args
        self.assertEqual(kwargs["domain"], "alarm_control_panel")
        self.assertEqual(kwargs["service"], "alarm_arm_home")
        self.assertEqual(kwargs["target"], {"entity_id": "alarm_control_panel.home"})
        self.assertEqual(kwargs["service_data"], {"code": "1234"})
        self.assertEqual(kwargs["timeout_seconds"], 1.5)
