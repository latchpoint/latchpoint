from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from integrations_home_assistant import api as ha_api
from integrations_home_assistant.impl import build_client_api_url


class BuildClientApiUrlTests(SimpleTestCase):
    """`homeassistant_api.Client`'s first argument is `api_url` and is used verbatim as the
    endpoint prefix. Handing it our bare base_url pointed it at Home Assistant's frontend:
    `get_config()` became `GET {base_url}/config`, an SPA route that answers 200 with
    text/html, so every call raised ProcessorNotFoundError and fell back to raw HTTP."""

    def test_appends_api_to_bare_base_url(self) -> None:
        self.assertEqual(build_client_api_url("http://ha.local:8123"), "http://ha.local:8123/api")

    def test_strips_trailing_slash_before_appending(self) -> None:
        self.assertEqual(build_client_api_url("http://ha.local:8123/"), "http://ha.local:8123/api")

    def test_does_not_double_an_existing_api_suffix(self) -> None:
        self.assertEqual(build_client_api_url("http://ha.local:8123/api"), "http://ha.local:8123/api")
        self.assertEqual(build_client_api_url("http://ha.local:8123/api/"), "http://ha.local:8123/api")

    def test_handles_https_and_paths(self) -> None:
        self.assertEqual(build_client_api_url("https://ha.example.com"), "https://ha.example.com/api")
        self.assertEqual(build_client_api_url("https://example.com/ha"), "https://example.com/ha/api")

    def test_blank_input_returns_blank(self) -> None:
        self.assertEqual(build_client_api_url(""), "")
        self.assertEqual(build_client_api_url("   "), "")

    def test_never_produces_the_frontend_config_route(self) -> None:
        """Regression guard: `{api_url}/config` must land on the REST API, not the SPA."""
        api_url = build_client_api_url("http://ha.local:8123")
        self.assertEqual(f"{api_url}/config", "http://ha.local:8123/api/config")


class GetClientUsesApiUrlTests(SimpleTestCase):
    """Both client construction sites must pass the /api-suffixed URL, not the raw base_url."""

    def test_api_module_get_client_passes_api_url(self) -> None:
        fake_client_cls = lambda *args, **kwargs: ("client", args, kwargs)  # noqa: E731

        with patch.object(ha_api, "_import_client", return_value=fake_client_cls):
            result = ha_api._get_client(base_url="http://ha.local:8123", token="tok")

        self.assertEqual(result[1], ("http://ha.local:8123/api", "tok"))

    def test_gateway_get_client_passes_api_url(self) -> None:
        from alarm.gateways.home_assistant import DefaultHomeAssistantGateway

        fake_client_cls = lambda *args, **kwargs: ("client", args, kwargs)  # noqa: E731
        gateway = DefaultHomeAssistantGateway()

        with patch.object(DefaultHomeAssistantGateway, "_import_client", return_value=fake_client_cls):
            result = gateway._get_client(base_url="http://ha.local:8123", token="tok")

        self.assertEqual(result[1], ("http://ha.local:8123/api", "tok"))

    def test_returns_none_without_base_url_or_token(self) -> None:
        fake_client_cls = lambda *args, **kwargs: ("client", args, kwargs)  # noqa: E731

        with patch.object(ha_api, "_import_client", return_value=fake_client_cls):
            self.assertIsNone(ha_api._get_client(base_url="", token="tok"))
            self.assertIsNone(ha_api._get_client(base_url="http://ha.local:8123", token=""))
