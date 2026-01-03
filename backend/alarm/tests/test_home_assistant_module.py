from __future__ import annotations

import io
import json
from datetime import timezone as dt_timezone
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from django.test import SimpleTestCase

from integrations_home_assistant import api as home_assistant
from integrations_home_assistant.connection import clear_cached_connection, set_cached_connection


class _DummyResponse:
    def __init__(self, *, status: int, headers: dict[str, str] | None = None, body: bytes = b""):
        self.status = status
        self.headers = headers or {}
        self._body = body

    def read(self, n: int = -1) -> bytes:
        if n == -1:
            return self._body
        return self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class HomeAssistantModuleTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        clear_cached_connection()

    def tearDown(self):
        clear_cached_connection()
        super().tearDown()

    def _set_configured_connection(self, *, base_url: str = "http://ha:8123", token: str = "token"):
        set_cached_connection(
            {
                "enabled": True,
                "base_url": base_url,
                "token": token,
                "connect_timeout_seconds": 2,
            }
        )

    def test_get_status_returns_not_configured_when_missing_settings(self):
        status = home_assistant.get_status()
        self.assertFalse(status.configured)
        self.assertFalse(status.reachable)
        self.assertIsNone(status.base_url)

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_get_status_raw_http_success_json_content_type(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123/", token="token")
        mock_urlopen.return_value = _DummyResponse(
            status=200,
            headers={"Content-Type": "application/json; charset=utf-8"},
            body=b'{"message":"API running."}',
        )
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertTrue(status.reachable)
        self.assertEqual(status.base_url, "http://ha:8123/")
        request = mock_urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/"))

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_get_status_raw_http_non_json_content_type_marks_unreachable(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_urlopen.return_value = _DummyResponse(
            status=200,
            headers={"Content-Type": "text/plain"},
            body=b"hello",
        )
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertIn("Unexpected content-type", status.error or "")

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_get_status_raw_http_http_error_sets_http_code(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        error = HTTPError(
            "http://ha:8123/api/",
            401,
            "Unauthorized",
            hdrs={"Content-Type": "application/json"},
            fp=io.BytesIO(b'{"message":"Unauthorized"}'),
        )
        mock_urlopen.side_effect = error
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertEqual(status.error, "HTTP 401")

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_get_status_raw_http_url_error_sets_reason(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_urlopen.side_effect = URLError("no route")
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertEqual(status.error, "no route")

    def test_ensure_available_raises_when_not_configured(self):
        with self.assertRaises(home_assistant.HomeAssistantNotConfigured):
            home_assistant.ensure_available()

    @patch("integrations_home_assistant.api.get_status")
    def test_ensure_available_raises_when_not_reachable(self, mock_get_status):
        mock_get_status.return_value = home_assistant.HomeAssistantStatus(
            configured=True,
            reachable=False,
            base_url="http://ha:8123",
            error="boom",
        )
        with self.assertRaises(home_assistant.HomeAssistantNotReachable) as ctx:
            home_assistant.ensure_available()
        self.assertEqual(getattr(ctx.exception, "error", None), "boom")

    def test_list_entities_returns_empty_when_not_configured(self):
        self.assertEqual(home_assistant.list_entities(), [])

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_list_entities_raw_http_parses_entities(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        payload = [
            {
                "entity_id": "binary_sensor.front_door",
                "state": "off",
                "attributes": {"friendly_name": "Front Door", "device_class": "door"},
                "last_changed": "2025-01-01T00:00:00Z",
            }
        ]
        mock_urlopen.return_value = _DummyResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode("utf-8"),
        )
        entities = home_assistant.list_entities(timeout_seconds=0.01)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["entity_id"], "binary_sensor.front_door")
        self.assertEqual(entities[0]["domain"], "binary_sensor")
        self.assertEqual(entities[0]["name"], "Front Door")
        request = mock_urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/states"))

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_list_entities_raw_http_non_list_payload_returns_empty(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_urlopen.return_value = _DummyResponse(
            status=200,
            headers={"Content-Type": "application/json"},
            body=b'{"not":"a list"}',
        )
        self.assertEqual(home_assistant.list_entities(timeout_seconds=0.01), [])

    def test_call_service_raises_when_not_configured(self):
        with self.assertRaises(RuntimeError):
            home_assistant.call_service(domain="alarm_control_panel", service="alarm_arm_home")

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_call_service_raw_http_raises_on_non_2xx(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_urlopen.return_value = _DummyResponse(status=500, headers={"Content-Type": "application/json"})
        with self.assertRaises(RuntimeError):
            home_assistant.call_service(domain="alarm_control_panel", service="alarm_arm_home", timeout_seconds=0.01)

    @patch("integrations_home_assistant.api._get_client", return_value=None)
    @patch("integrations_home_assistant.api.urlopen")
    def test_call_service_raw_http_sends_top_level_payload(self, mock_urlopen, _mock_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_urlopen.return_value = _DummyResponse(status=200, headers={"Content-Type": "application/json"})

        home_assistant.call_service(
            domain="notify",
            service="mobile_app_phone",
            target={"entity_id": "notify.mobile_app_phone"},
            service_data={"title": "t", "message": "m", "data": {"a": 1}},
            timeout_seconds=0.01,
        )

        request = mock_urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/services/notify/mobile_app_phone"))
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"entity_id": "notify.mobile_app_phone", "title": "t", "message": "m", "data": {"a": 1}},
        )

    @patch("integrations_home_assistant.api.urlopen")
    @patch("integrations_home_assistant.api._get_client")
    def test_call_service_uses_client_when_available(self, mock_get_client, mock_urlopen):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        class _Client:
            def __init__(self):
                self.calls = []

            def call_service(self, domain, service, **payload):
                self.calls.append((domain, service, payload))

        client = _Client()
        mock_get_client.return_value = client
        home_assistant.call_service(
            domain="alarm_control_panel",
            service="alarm_arm_home",
            target={"entity_id": "alarm_control_panel.home"},
            service_data={"code": "1234"},
        )
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][0], "alarm_control_panel")
        self.assertEqual(client.calls[0][1], "alarm_arm_home")
        self.assertEqual(
            client.calls[0][2],
            {"entity_id": "alarm_control_panel.home", "code": "1234"},
        )
        mock_urlopen.assert_not_called()
