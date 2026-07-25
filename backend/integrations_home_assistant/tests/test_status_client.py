"""Reachability checks via the ``homeassistant_api`` client (ADR-0105 Phase 1, AC-2/AC-3).

Three layers:

- ``HomeAssistantStatusCaseTests`` pins the ``HomeAssistantStatus`` produced for every case,
  by full dataclass equality, with a scripted client injected.
- ``HomeAssistantStatusLiveClientTests`` runs the *real* ``_StatusClient`` against a loopback
  server that also serves Home Assistant's SPA route, so the ``api_url`` defect behind #85/#86
  fails the suite instead of the deploy.
- ``HomeAssistantStatusTimeoutTests`` keeps AC-2 verified: the per-call timeout has to reach
  the socket, or an unresponsive Home Assistant hangs a scheduler tick.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from django.test import SimpleTestCase
from homeassistant_api.errors import (
    EndpointNotFoundError,
    InternalServerError,
    ProcessorNotFoundError,
    RequestTimeoutError,
    UnauthorizedError,
    UnexpectedStatusCodeError,
)

from integrations_home_assistant import impl

BASE_URL = "http://ha:8123"
TOKEN = "token"


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


def _factory_for(client: Any, calls: list[dict[str, Any]] | None = None):
    """Return a ``client_factory`` yielding ``client`` and recording how it was called."""

    def factory(*, api_url: str, token: str, timeout_seconds: float) -> Any:
        if calls is not None:
            calls.append({"api_url": api_url, "token": token, "timeout_seconds": timeout_seconds})
        return client

    return factory


class HomeAssistantStatusCaseTests(SimpleTestCase):
    """AC-3: the status snapshot for every outcome, compared whole rather than field by field."""

    def _status(self, client: Any, **kwargs: Any) -> impl.HomeAssistantStatus:
        return impl.get_status(
            base_url=kwargs.pop("base_url", BASE_URL),
            token=kwargs.pop("token", TOKEN),
            client_factory=_factory_for(client, kwargs.pop("calls", None)),
            **kwargs,
        )

    def test_reachable(self):
        status = self._status(_FakeStatusClient(status_code=200, content_type="application/json"))
        self.assertEqual(status, impl.HomeAssistantStatus(configured=True, reachable=True, base_url=BASE_URL))

    def test_not_configured_without_base_url(self):
        status = impl.get_status(base_url="", token=TOKEN)
        self.assertEqual(status, impl.HomeAssistantStatus(configured=False, reachable=False, base_url=None))

    def test_not_configured_without_token_keeps_base_url(self):
        status = impl.get_status(base_url=BASE_URL, token="   ")
        self.assertEqual(status, impl.HomeAssistantStatus(configured=False, reachable=False, base_url=BASE_URL))

    def test_unreachable_transport_error_reports_reason(self):
        # niquests' RequestException subclasses OSError, as urllib's URLError did.
        status = self._status(_FakeStatusClient(raises=ConnectionError("connection refused")))
        self.assertEqual(
            status,
            impl.HomeAssistantStatus(configured=True, reachable=False, base_url=BASE_URL, error="connection refused"),
        )

    def test_unreachable_timeout_reports_reason(self):
        exc = RequestTimeoutError("Home Assistant did not respond in time", url=f"{BASE_URL}/api/")
        status = self._status(_FakeStatusClient(raises=exc))
        self.assertEqual(
            status,
            impl.HomeAssistantStatus(configured=True, reachable=False, base_url=BASE_URL, error=str(exc)),
        )

    def test_unreachable_when_client_cannot_be_built(self):
        # The library rejects an api_url with no http(s) scheme before any request is made.
        def factory(**_kwargs: Any) -> Any:
            raise ValueError("Unknown scheme ha in ha:8123/api/")

        status = impl.get_status(base_url="ha:8123", token=TOKEN, client_factory=factory)
        self.assertEqual(
            status,
            impl.HomeAssistantStatus(
                configured=True, reachable=False, base_url="ha:8123", error="Unknown scheme ha in ha:8123/api/"
            ),
        )

    def test_http_error_maps_status_code_not_exception_type(self):
        # The library reports HTTP failures as exception types and drops the numeric code, so
        # each has to come back as the same "HTTP <code>" string raw HTTP always produced.
        cases = [
            (401, UnauthorizedError(), "HTTP 401"),
            (404, EndpointNotFoundError(f"{BASE_URL}/api/"), "HTTP 404"),
            (500, InternalServerError(500, "boom"), "HTTP 500"),
            (418, UnexpectedStatusCodeError(418), "HTTP 418"),
        ]
        for status_code, exc, expected_error in cases:
            with self.subTest(status_code=status_code):
                client = _FakeStatusClient(status_code=status_code, content_type="text/plain", raises=exc)
                status = self._status(client)
                self.assertEqual(
                    status,
                    impl.HomeAssistantStatus(configured=True, reachable=False, base_url=BASE_URL, error=expected_error),
                )

    def test_unparseable_2xx_body_reports_content_type(self):
        cases = [
            ("text/html", ProcessorNotFoundError("No response processor found for mimetype 'text/html'.")),
            ("text/plain; charset=utf-8", TypeError("Expected dict response, got str")),
        ]
        for content_type, exc in cases:
            with self.subTest(content_type=content_type):
                client = _FakeStatusClient(status_code=200, content_type=content_type, raises=exc)
                status = self._status(client)
                self.assertEqual(
                    status,
                    impl.HomeAssistantStatus(
                        configured=True,
                        reachable=False,
                        base_url=BASE_URL,
                        error=f"Unexpected content-type from Home Assistant: {content_type}",
                    ),
                )

    def test_json_body_the_library_cannot_read_reports_the_error_itself(self):
        # 2xx *and* JSON: not a content-type problem, so don't mislabel it as one.
        client = _FakeStatusClient(
            status_code=200,
            content_type="application/json",
            raises=TypeError("Expected dict response, got list"),
        )
        status = self._status(client)
        self.assertEqual(
            status,
            impl.HomeAssistantStatus(
                configured=True, reachable=False, base_url=BASE_URL, error="Expected dict response, got list"
            ),
        )

    def test_api_not_reporting_running_is_unreachable(self):
        # 200 JSON, but not {"message": "API running."}. Raw HTTP never read the body and would
        # have called this reachable; an unrecognised answer on /api/ is reported, not assumed.
        client = _FakeStatusClient(status_code=200, content_type="application/json", running=False)
        status = self._status(client)
        self.assertEqual(
            status,
            impl.HomeAssistantStatus(
                configured=True,
                reachable=False,
                base_url=BASE_URL,
                error="Home Assistant did not report the API as running.",
            ),
        )

    def test_client_is_closed_on_success_and_on_failure(self):
        for raises in (None, ConnectionError("boom")):
            with self.subTest(raises=raises):
                client = _FakeStatusClient(status_code=200, content_type="application/json", raises=raises)
                self._status(client)
                self.assertTrue(client.closed)

    def test_token_and_timeout_reach_the_client(self):
        calls: list[dict[str, Any]] = []
        client = _FakeStatusClient(status_code=200, content_type="application/json")
        self._status(client, timeout_seconds=7.5, calls=calls)
        self.assertEqual(calls, [{"api_url": f"{BASE_URL}/api/", "token": TOKEN, "timeout_seconds": 7.5}])

    def test_base_url_is_echoed_back_unchanged(self):
        client = _FakeStatusClient(status_code=200, content_type="application/json")
        status = self._status(client, base_url="http://ha:8123/")
        self.assertEqual(status.base_url, "http://ha:8123/")


class HomeAssistantApiUrlTests(SimpleTestCase):
    """The library uses its first argument verbatim, so the /api suffix is ours to add."""

    def test_suffix_is_added_once(self):
        cases = [
            ("http://ha:8123", "http://ha:8123/api/"),
            ("http://ha:8123/", "http://ha:8123/api/"),
            ("  http://ha:8123//  ", "http://ha:8123/api/"),
            ("http://ha:8123/api", "http://ha:8123/api/"),
            ("http://ha:8123/api/", "http://ha:8123/api/"),
            ("http://ha:8123/API", "http://ha:8123/API/"),
            ("https://ha.example.com/hass", "https://ha.example.com/hass/api/"),
        ]
        for base_url, expected in cases:
            with self.subTest(base_url=base_url):
                self.assertEqual(impl._api_url(base_url), expected)

    def test_status_builds_the_client_with_the_api_url(self):
        calls: list[dict[str, Any]] = []
        client = _FakeStatusClient(status_code=200, content_type="application/json")
        impl.get_status(
            base_url="http://ha:8123",
            token=TOKEN,
            client_factory=_factory_for(client, calls),
        )
        self.assertEqual(calls[0]["api_url"], "http://ha:8123/api/")


class HomeAssistantEnsureAvailableTests(SimpleTestCase):
    """AC-3: the domain exceptions still fire at the same boundaries."""

    def test_raises_not_configured(self):
        with self.assertRaises(impl.HomeAssistantNotConfigured):
            impl.ensure_available(base_url="", token="")

    def test_raises_not_reachable_carrying_the_error(self):
        client = _FakeStatusClient(status_code=401, content_type="text/plain", raises=UnauthorizedError())
        with self.assertRaises(impl.HomeAssistantNotReachable) as ctx:
            impl.ensure_available(base_url=BASE_URL, token=TOKEN, client_factory=_factory_for(client))
        self.assertEqual(ctx.exception.error, "HTTP 401")

    def test_returns_status_when_reachable(self):
        client = _FakeStatusClient(status_code=200, content_type="application/json")
        status = impl.ensure_available(base_url=BASE_URL, token=TOKEN, client_factory=_factory_for(client))
        self.assertEqual(status, impl.HomeAssistantStatus(configured=True, reachable=True, base_url=BASE_URL))


# Path -> (status, content-type, body). "/" and "/config" answer the way Home Assistant's Single
# Page App does, so a client built with the un-suffixed base_url reproduces the #86 defect.
_SPA_HTML = "<!DOCTYPE html><html><body>home assistant frontend</body></html>"
_ROUTES: dict[str, tuple[int, str, str]] = {
    "/": (200, "text/html", _SPA_HTML),
    "/config": (200, "text/html", _SPA_HTML),
    "/api/": (200, "application/json", json.dumps({"message": "API running."})),
    "/unauthorized/api/": (401, "text/plain", "401: Unauthorized"),
    "/spa/api/": (200, "text/html", _SPA_HTML),
    "/broken/api/": (500, "text/plain", "500: Internal Server Error"),
    "/stranger/api/": (200, "application/json", json.dumps({"message": "who knows"})),
}


class _StubHomeAssistantHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's naming
        status, content_type, body = _ROUTES.get(self.path, (404, "text/plain", "404: Not Found"))
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args, **kwargs):
        """Keep the stub server out of the test output."""


class HomeAssistantStatusLiveClientTests(SimpleTestCase):
    """The real ``_StatusClient``, no mocks, against a Home-Assistant-shaped loopback server."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHomeAssistantHandler)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls.base_url = f"http://127.0.0.1:{cls._server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)
        super().tearDownClass()

    def test_reachable_because_the_client_requests_api_not_the_spa_route(self):
        # Regression guard for #85/#86: this server answers "/" with 200 text/html exactly as
        # Home Assistant does, so a client built with the bare base_url comes back unreachable
        # with a ProcessorNotFoundError instead of reachable.
        status = impl.get_status(base_url=self.base_url, token=TOKEN, timeout_seconds=5.0)
        self.assertEqual(
            status,
            impl.HomeAssistantStatus(configured=True, reachable=True, base_url=self.base_url),
        )

    def test_base_url_already_ending_in_api_is_not_doubled(self):
        # /api/api/ is not routed, so a doubled suffix would come back as HTTP 404.
        status = impl.get_status(base_url=f"{self.base_url}/api", token=TOKEN, timeout_seconds=5.0)
        self.assertTrue(status.reachable, msg=f"expected reachable, got error={status.error!r}")

    def test_live_http_error_reports_the_status_code(self):
        status = impl.get_status(base_url=f"{self.base_url}/unauthorized", token=TOKEN, timeout_seconds=5.0)
        self.assertEqual(status.error, "HTTP 401")
        self.assertFalse(status.reachable)

    def test_live_server_error_reports_the_status_code(self):
        status = impl.get_status(base_url=f"{self.base_url}/broken", token=TOKEN, timeout_seconds=5.0)
        self.assertEqual(status.error, "HTTP 500")

    def test_live_html_answer_reports_the_content_type(self):
        status = impl.get_status(base_url=f"{self.base_url}/spa", token=TOKEN, timeout_seconds=5.0)
        self.assertEqual(status.error, "Unexpected content-type from Home Assistant: text/html")

    def test_live_unrecognised_json_answer_is_unreachable(self):
        status = impl.get_status(base_url=f"{self.base_url}/stranger", token=TOKEN, timeout_seconds=5.0)
        self.assertEqual(status.error, "Home Assistant did not report the API as running.")

    def test_live_connection_refused_is_unreachable(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            unused_port = probe.getsockname()[1]
        status = impl.get_status(base_url=f"http://127.0.0.1:{unused_port}", token=TOKEN, timeout_seconds=5.0)
        self.assertFalse(status.reachable)
        self.assertTrue(status.configured)
        self.assertTrue(status.error)

    def test_ensure_available_raises_not_reachable_against_a_live_401(self):
        with self.assertRaises(impl.HomeAssistantNotReachable) as ctx:
            impl.ensure_available(base_url=f"{self.base_url}/unauthorized", token=TOKEN, timeout_seconds=5.0)
        self.assertEqual(ctx.exception.error, "HTTP 401")


class HomeAssistantStatusTimeoutTests(SimpleTestCase):
    """AC-2: the per-call timeout must reach the socket, not just be accepted as a kwarg.

    ``check_api_running()`` takes no arguments, so the only seam is the client's
    ``global_request_kwargs``. A host that completes the TCP handshake and then never answers is
    the case that hangs a scheduler tick, and it is the one that has to be bounded.
    """

    def setUp(self):
        super().setUp()
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._accepted: list[socket.socket] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_and_stall, daemon=True)
        self._thread.start()

    def tearDown(self):
        self._stop.set()
        self._listener.close()
        for conn in self._accepted:
            conn.close()
        self._thread.join(timeout=5)
        super().tearDown()

    def _accept_and_stall(self):
        """Accept connections and then do nothing at all with them."""
        while not self._stop.is_set():
            try:
                conn, _addr = self._listener.accept()
            except OSError:
                return
            self._accepted.append(conn)

    def test_status_gives_up_within_the_configured_timeout(self):
        base_url = f"http://127.0.0.1:{self._listener.getsockname()[1]}"
        started = time.monotonic()
        status = impl.get_status(base_url=base_url, token=TOKEN, timeout_seconds=0.5)
        elapsed = time.monotonic() - started

        self.assertFalse(status.reachable)
        self.assertTrue(status.configured)
        self.assertLess(elapsed, 5.0, msg=f"timeout was not enforced: took {elapsed:.2f}s")
