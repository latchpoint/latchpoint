from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from rest_framework.authtoken.models import Token

from accounts.models import User
from config.domain_exceptions import UnauthorizedError


class InvalidCredentials(UnauthorizedError):
    pass


class InvalidRefreshToken(UnauthorizedError):
    pass


@dataclass(frozen=True)
class LoginResult:
    user: User
    token: Token


def login(*, request, email: str, password: str) -> LoginResult:
    """Authenticate credentials and issue/reuse a DRF token (compatibility)."""
    user = authenticate(request, username=email, password=password)
    if not user:
        raise InvalidCredentials("Invalid credentials.")
    token, _ = Token.objects.get_or_create(user=user)
    update_last_login(None, user)
    return LoginResult(user=user, token=token)


def refresh_token(*, refresh: str) -> Token:
    """Validate an existing token key and return it (legacy refresh flow)."""
    token = Token.objects.filter(key=refresh).first()
    if not token:
        raise InvalidRefreshToken("Invalid refresh token.")
    return token


def logout(*, user: User) -> None:
    """Delete any existing token for the user (best-effort)."""
    Token.objects.filter(user=user).delete()
