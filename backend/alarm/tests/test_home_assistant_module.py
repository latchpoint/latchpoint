from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase
from homeassistant_api.errors import ProcessorNotFoundError, UnauthorizedError
from integrations_home_assistant import api as home_assistant
from integrations_home_assistant.connection import clear_cached_connection, set_cached_connection


class _FakeStatusClient:
    """Stands in for ``impl._StatusClient``: the attributes it captures plus a scripted outcome."""

    def __init__(
        self,
        *,
        status_code: int | None = None,
        content_type: str = "",
        body_preview: str = "",
        running: bool = True,
        raises: BaseException | None = None,
    ):
        self.last_status_code = status_code
        self.last_content_type = content_type
        self.last_body_preview = body_preview
        self._running = running
        self._raises = raises
        self.closed = False

    def check_api_running(self) -> bool:
        if self._raises is not None:
            raise self._raises
        return self._running

    def close(self) -> None:
        self.closed = True


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
        patcher = getattr(self, "_settings_patcher", None)
        if patcher is not None:
            patcher.stop()
        clear_cached_connection()
        super().tearDown()

    def _set_configured_connection(self, *, base_url: str = "http://ha:8123", token: str = "token"):
        # Mock get_ha_settings (SimpleTestCase has no DB access)
        self._settings_patcher = patch(
            "integrations_home_assistant.views.get_ha_settings",
            return_value={
                "enabled": True,
                "base_url": base_url,
                "token": token,
                "connect_timeout_seconds": 2,
            },
        )
        self._settings_patcher.start()
        set_cached_connection()

    def test_get_status_returns_not_configured_when_missing_settings(self):
        status = home_assistant.get_status()
        self.assertFalse(status.configured)
        self.assertFalse(status.reachable)
        self.assertIsNone(status.base_url)

    @patch("integrations_home_assistant.impl._build_status_client")
    def test_get_status_client_success_marks_reachable(self, mock_build_client):
        self._set_configured_connection(base_url="http://ha:8123/", token="token")
        mock_build_client.return_value = _FakeStatusClient(status_code=200, content_type="application/json")
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertTrue(status.reachable)
        self.assertEqual(status.base_url, "http://ha:8123/")
        # The client must be built with the /api-suffixed URL: the bare base_url is Home
        # Assistant's SPA route, which is what made the old client branch dead (#86).
        self.assertEqual(mock_build_client.call_args.kwargs["api_url"], "http://ha:8123/api/")

    @patch("integrations_home_assistant.impl._build_status_client")
    def test_get_status_non_json_content_type_marks_unreachable(self, mock_build_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        # 200 text/plain: the library parses it to a str, then its "expected dict" guard raises.
        mock_build_client.return_value = _FakeStatusClient(
            status_code=200,
            content_type="text/plain",
            body_preview="hello",
            raises=TypeError("Expected dict response, got str"),
        )
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertIn("Unexpected content-type", status.error or "")

    @patch("integrations_home_assistant.impl._build_status_client")
    def test_get_status_html_content_type_marks_unreachable(self, mock_build_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        # Home Assistant's SPA route answers 200 text/html and the library has no processor
        # for that mimetype — the exact symptom the dead client branches produced forever.
        mock_build_client.return_value = _FakeStatusClient(
            status_code=200,
            content_type="text/html",
            body_preview="<html>",
            raises=ProcessorNotFoundError("No response processor found for mimetype 'text/html'."),
        )
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertEqual(status.error, "Unexpected content-type from Home Assistant: text/html")

    @patch("integrations_home_assistant.impl._build_status_client")
    def test_get_status_http_error_sets_http_code(self, mock_build_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_build_client.return_value = _FakeStatusClient(
            status_code=401,
            content_type="text/plain",
            raises=UnauthorizedError(),
        )
        status = home_assistant.get_status(timeout_seconds=0.01)
        self.assertTrue(status.configured)
        self.assertFalse(status.reachable)
        self.assertEqual(status.error, "HTTP 401")

    @patch("integrations_home_assistant.impl._build_status_client")
    def test_get_status_transport_error_sets_reason(self, mock_build_client):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        # niquests' RequestException subclasses OSError, exactly as urllib's URLError did, so
        # connect/DNS/TLS failures still surface their low-level reason.
        mock_build_client.return_value = _FakeStatusClient(raises=ConnectionError("no route"))
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

    @patch("integrations_home_assistant.api.urlopen")
    def test_list_entities_raw_http_parses_entities(self, mock_urlopen):
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

    @patch("integrations_home_assistant.api.urlopen")
    def test_list_entities_raw_http_non_list_payload_returns_empty(self, mock_urlopen):
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

    @patch("integrations_home_assistant.api.urlopen")
    def test_call_service_raw_http_raises_on_non_2xx(self, mock_urlopen):
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_urlopen.return_value = _DummyResponse(status=500, headers={"Content-Type": "application/json"})
        with self.assertRaises(RuntimeError):
            home_assistant.call_service(domain="alarm_control_panel", service="alarm_arm_home", timeout_seconds=0.01)

    @patch("integrations_home_assistant.api.urlopen")
    def test_call_service_raw_http_sends_top_level_payload(self, mock_urlopen):
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
    def test_call_service_uses_rest_not_client(self, mock_urlopen):
        # The homeassistant_api client exposes trigger_service (not call_service), so the old client
        # branch AttributeError'd on every call and fell through to REST. call_service now POSTs directly.
        self._set_configured_connection(base_url="http://ha:8123", token="token")
        mock_urlopen.return_value = _DummyResponse(status=200, headers={"Content-Type": "application/json"}, body=b"[]")

        home_assistant.call_service(
            domain="alarm_control_panel",
            service="alarm_arm_home",
            target={"entity_id": "alarm_control_panel.home"},
            service_data={"code": "1234"},
        )

        mock_urlopen.assert_called_once()
        request = mock_urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/api/services/alarm_control_panel/alarm_arm_home"))
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"entity_id": "alarm_control_panel.home", "code": "1234"},
        )
