from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token


def token_ttl_seconds() -> int:
    """Configured token lifetime in seconds; 0 (or negative) disables expiry."""
    return getattr(settings, "AUTH_TOKEN_TTL_SECONDS", 0)


def token_is_expired(token: Token) -> bool:
    """Return True if the token is older than the configured TTL."""
    ttl = token_ttl_seconds()
    if ttl <= 0:
        return False
    return timezone.now() >= token.created + timedelta(seconds=ttl)


class ExpiringTokenAuthentication(TokenAuthentication):
    """DRF token auth that rejects (and deletes) tokens past ``AUTH_TOKEN_TTL_SECONDS``."""

    def authenticate_credentials(self, key):
        """Resolve the token, then fail closed and delete it if it has expired."""
        user, token = super().authenticate_credentials(key)
        if token_is_expired(token):
            token.delete()
            raise exceptions.AuthenticationFailed("Token has expired.")
        return user, token


class BearerTokenAuthentication(ExpiringTokenAuthentication):
    keyword = "Bearer"
