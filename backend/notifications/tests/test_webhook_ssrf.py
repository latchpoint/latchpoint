from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from notifications.handlers.webhook import WebhookHandler
from notifications.ssrf import BlockedAddressError, _ip_is_blocked, validate_outbound_url


class SsrfGuardTests(SimpleTestCase):
    def test_blocks_loopback(self):
        with self.assertRaises(BlockedAddressError):
            validate_outbound_url("http://127.0.0.1/hook")

    def test_blocks_link_local_metadata(self):
        with self.assertRaises(BlockedAddressError):
            validate_outbound_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_non_http_scheme(self):
        with self.assertRaises(BlockedAddressError):
            validate_outbound_url("file:///etc/passwd")

    def test_allows_public_ip(self):
        # IP literals don't hit DNS; this must not raise.
        validate_outbound_url("https://8.8.8.8/hook")

    def test_allows_private_lan_by_default(self):
        validate_outbound_url("http://192.168.1.50/hook")

    @override_settings(NOTIFICATIONS_WEBHOOK_BLOCK_PRIVATE=True)
    def test_blocks_private_when_configured(self):
        with self.assertRaises(BlockedAddressError):
            validate_outbound_url("http://192.168.1.50/hook")

    def test_blocks_ipv4_mapped_ipv6(self):
        # ::ffff:127.0.0.1 / ::ffff:169.254.169.254 must be judged by the embedded IPv4 —
        # ipaddress.is_loopback / is_link_local are False for the v6-wrapped form.
        self.assertTrue(_ip_is_blocked("::ffff:127.0.0.1", block_private=False))
        self.assertTrue(_ip_is_blocked("::ffff:169.254.169.254", block_private=False))

    def test_blocks_ipv4_mapped_loopback_via_url(self):
        with self.assertRaises(BlockedAddressError):
            validate_outbound_url("http://[::ffff:127.0.0.1]/hook")


class WebhookHandlerSsrfTests(SimpleTestCase):
    def test_send_refuses_internal_target(self):
        handler = WebhookHandler()
        result = handler.send({"url": "http://127.0.0.1:8000/internal", "method": "POST"}, "msg")
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "BLOCKED_URL")
