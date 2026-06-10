from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.utils import timezone
from rest_framework.authtoken.models import Token

from accounts.authentication import token_is_expired
from accounts.models import User
from config.domain_exceptions import RateLimitedError, UnauthorizedError


class InvalidCredentials(UnauthorizedError):
    pass


class AccountLocked(RateLimitedError):
    pass


class InvalidRefreshToken(UnauthorizedError):
    pass


@dataclass(frozen=True)
class LoginResult:
    user: User
    token: Token


def _lockout_threshold() -> int:
    return getattr(settings, "ACCOUNT_LOCKOUT_THRESHOLD", 5)


def _lockout_window() -> int:
    return getattr(settings, "ACCOUNT_LOCKOUT_WINDOW_SECONDS", 900)


def _register_failed_login(user: User, now) -> None:
    """Increment the failed-attempt counter and lock the account once the threshold is hit."""
    threshold = _lockout_threshold()
    attempts = (user.failed_login_attempts or 0) + 1
    if threshold and attempts >= threshold:
        # Lock and reset the counter so a fresh attempt budget applies after expiry.
        user.failed_login_attempts = 0
        user.locked_until = now + timedelta(seconds=_lockout_window())
    else:
        user.failed_login_attempts = attempts
    user.save(update_fields=["failed_login_attempts", "locked_until"])


def _issue_token(user: User) -> Token:
    """Return the user's token, rotating it if the existing one has expired."""
    token = Token.objects.filter(user=user).first()
    if token is not None and token_is_expired(token):
        token.delete()
        token = None
    if token is None:
        token = Token.objects.create(user=user)
    return token


def login(*, request, email: str, password: str) -> LoginResult:
    """Authenticate credentials and issue/reuse a DRF token (compatibility).

    Enforces account lockout: the lookup user's ``locked_until`` is honored before
    authentication, failed attempts increment the counter, and a successful login
    clears it.
    """
    now = timezone.now()
    lookup_user = User.objects.filter(email__iexact=email).first()
    if lookup_user and lookup_user.locked_until and lookup_user.locked_until > now:
        raise AccountLocked("Account temporarily locked due to too many failed login attempts.")

    user = authenticate(request, username=email, password=password)
    if not user:
        if lookup_user is not None:
            _register_failed_login(lookup_user, now)
        raise InvalidCredentials("Invalid credentials.")

    if user.failed_login_attempts or user.locked_until:
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_attempts", "locked_until"])

    token = _issue_token(user)
    update_last_login(None, user)
    return LoginResult(user=user, token=token)


def refresh_token(*, refresh: str) -> Token:
    """Validate an existing token key and return it (legacy refresh flow)."""
    token = Token.objects.filter(key=refresh).first()
    if not token or token_is_expired(token):
        raise InvalidRefreshToken("Invalid refresh token.")
    return token


def logout(*, user: User) -> None:
    """Delete any existing token for the user (best-effort)."""
    Token.objects.filter(user=user).delete()
