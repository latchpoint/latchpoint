from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth.hashers import check_password

from accounts.models import User, UserCode
from config.domain_exceptions import ValidationError


class CodeValidationError(ValidationError):
    pass


class CodeRequiredError(CodeValidationError):
    pass


class InvalidCodeError(CodeValidationError):
    pass


@dataclass(frozen=True)
class CodeValidationResult:
    code: UserCode


def _validate_code_format(*, raw_code: str) -> str:
    """Validate that the raw code looks like a PIN (digits-only validated elsewhere)."""
    if raw_code is None:
        raise CodeRequiredError("Code is required.")
    raw_code = str(raw_code).strip()
    if len(raw_code) < 4 or len(raw_code) > 8:
        raise InvalidCodeError("Invalid code.")
    return raw_code


def _validate_candidate(*, user: User, candidate: UserCode, raw_code: str, now) -> bool:
    """Return True if `raw_code` matches and passes candidate validity windows/limits."""
    if not check_password(raw_code, candidate.code_hash):
        return False
    if candidate.code_type == UserCode.CodeType.TEMPORARY:
        try:
            tz = ZoneInfo(getattr(user, "timezone", "UTC") or "UTC")
        except Exception:
            tz = dt_timezone.utc
        local_now = now.astimezone(tz)
        local_weekday = local_now.weekday()  # Monday=0
        if candidate.days_of_week is not None:
            allowed_mask = int(candidate.days_of_week)
            if (allowed_mask & (1 << local_weekday)) == 0:
                raise InvalidCodeError("Code is not valid today.")
        if candidate.window_start and candidate.window_end:
            local_time = local_now.timetz().replace(tzinfo=None)
            if local_time < candidate.window_start or local_time > candidate.window_end:
                raise InvalidCodeError("Code is not valid at this time.")
        if candidate.start_at and now < candidate.start_at:
            raise InvalidCodeError("Code is not active yet.")
        if candidate.end_at and now > candidate.end_at:
            raise InvalidCodeError("Code has expired.")
    return True


def validate_user_code(*, user: User, raw_code: str, now) -> CodeValidationResult:
    """Validate a code against a user's active codes."""
    raw_code = _validate_code_format(raw_code=raw_code)
    candidates = UserCode.objects.filter(user=user, is_active=True)
    for candidate in candidates:
        if _validate_candidate(user=user, candidate=candidate, raw_code=raw_code, now=now):
            return CodeValidationResult(code=candidate)
    raise InvalidCodeError("Invalid code.")


def validate_any_active_code(*, raw_code: str, now) -> CodeValidationResult:
    """
    Validate a code against any active code in the system.

    Intended for integration-style entry points (e.g., MQTT alarm panel) where there is no
    authenticated user context.
    """

    raw_code = _validate_code_format(raw_code=raw_code)
    candidates = UserCode.objects.filter(is_active=True).select_related("user")
    for candidate in candidates:
        user = getattr(candidate, "user", None)
        if user is None:
            continue
        if _validate_candidate(user=user, candidate=candidate, raw_code=raw_code, now=now):
            return CodeValidationResult(code=candidate)
    raise InvalidCodeError("Invalid code.")
