from __future__ import annotations

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError as DrfValidationError

from alarm.state_machine.errors import TransitionError
from config.exception_handler import custom_exception_handler
from integrations_zwavejs.manager import ZwavejsCommandValidationError
from transports_mqtt.manager import MqttPublishError
from alarm.gateways.home_assistant import HomeAssistantNotConfigured


class _DummyView:
    pass


class ExceptionHandlerTests(SimpleTestCase):
    def _handle(self, exc: Exception):
        response = custom_exception_handler(exc, {"view": _DummyView()})
        self.assertIsNotNone(response)
        return response

    def test_drf_validation_error_includes_envelope(self):
        response = self._handle(DrfValidationError({"name": ["This field is required."]}))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["status"], "validation_error")
        self.assertIn("name", response.data["error"]["details"])

    def test_transition_error_maps_to_conflict(self):
        response = self._handle(TransitionError("Invalid transition."))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["error"]["status"], "conflict")

    def test_gateway_not_configured_maps_to_503(self):
        response = self._handle(HomeAssistantNotConfigured("missing config"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["error"]["status"], "service_unavailable")
        self.assertEqual(response.data["error"].get("gateway"), "Home Assistant")

    def test_gateway_validation_error_maps_to_400_and_includes_gateway(self):
        response = self._handle(ZwavejsCommandValidationError("node_id must be a positive integer."))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"]["status"], "validation_error")
        self.assertEqual(response.data["error"].get("gateway"), "Z-Wave JS")

    def test_gateway_operation_error_includes_operation(self):
        response = self._handle(MqttPublishError("test/topic", "boom"))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data["error"]["status"], "gateway_error")
        self.assertEqual(response.data["error"].get("gateway"), "MQTT")
        self.assertEqual(response.data["error"].get("operation"), "publish to test/topic")
