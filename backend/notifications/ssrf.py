"""SSRF guard for user-configurable outbound URLs (webhook notifications).

The threat is a user (or a compromised low-privilege account) pointing a webhook at
the server's own internal services or a cloud metadata endpoint. We resolve the
target host and reject loopback, link-local (incl. 169.254.169.254), reserved,
unspecified and multicast addresses.

Private/LAN ranges (RFC1918) are allowed by default because this is a home-lab
product where webhooking another device on the local network is a normal use case.
Set ``NOTIFICATIONS_WEBHOOK_BLOCK_PRIVATE=True`` to also block those.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from django.conf import settings


class BlockedAddressError(ValueError):
    """Raised when an outbound URL resolves to a disallowed address."""


def _ip_is_blocked(ip_text: str, *, block_private: bool) -> bool:
    """Return True if the resolved IP is in a range we refuse to connect to."""
    ip = ipaddress.ip_address(ip_text)
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return True
    return bool(block_private and ip.is_private)


def validate_outbound_url(url: str) -> None:
    """Validate that ``url`` is an http(s) URL that does not resolve to an internal address.

    Raises ``BlockedAddressError`` otherwise. All addresses a hostname resolves to are
    checked, so a public name that resolves to an internal IP is still rejected.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedAddressError(f"Unsupported URL scheme: {parsed.scheme or '(none)'!r}")
    host = parsed.hostname
    if not host:
        raise BlockedAddressError("Webhook URL has no host.")

    block_private = getattr(settings, "NOTIFICATIONS_WEBHOOK_BLOCK_PRIVATE", False)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise BlockedAddressError(f"Could not resolve webhook host {host!r}.") from exc

    for info in infos:
        ip_text = info[4][0]
        if _ip_is_blocked(ip_text, block_private=block_private):
            raise BlockedAddressError(f"Refusing to connect to internal address {ip_text} (host {host!r}).")
