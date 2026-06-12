from __future__ import annotations

from django.utils import timezone

from accounts.models import UserCode
from accounts.use_cases import code_validation
from alarm import code_attempt_guard
from alarm.models import AlarmState
from alarm.state_machine.errors import CodeRequiredError, InvalidCodeError
from alarm.state_machine.events import record_code_used, record_failed_code
from alarm.state_machine.settings import get_active_settings_profile, get_setting_bool
from alarm.state_machine.transitions import arm, disarm
from config.domain_exceptions import (
    DomainError,
    RateLimitedError,
    UnauthorizedError,
    ValidationError,
)


class AlarmActionError(DomainError):
    pass


class InvalidTargetState(ValidationError):
    pass


class CodeRequired(ValidationError):
    pass


class InvalidCode(UnauthorizedError):
    pass


class AlarmCodeRateLimited(RateLimitedError):
    pass


class AlarmCodeLockedOut(RateLimitedError):
    pass


def _reject_if_locked_out(*, user, action: str, metadata: dict | None = None) -> None:
    """Refuse (with an audit event) when the panel is locked from too many failed codes."""
    locked, remaining = code_attempt_guard.is_locked_out()
    if not locked:
        return
    record_failed_code(
        user=user,
        action=action,
        metadata={"reason": "locked_out", **(metadata or {})},
    )
    raise AlarmCodeLockedOut(f"Too many failed code attempts. Locked out for {remaining} seconds.")


def _reject_if_rate_limited(*, user) -> None:
    """Refuse when this user has exceeded the configured alarm-code rate limit."""
    source_key = f"web:user:{getattr(user, 'id', None)}"
    if not code_attempt_guard.check_rate_limit(source_key):
        raise AlarmCodeRateLimited("Too many attempts. Try again later.")


ALLOWED_ARM_TARGET_STATES = {
    AlarmState.ARMED_HOME,
    AlarmState.ARMED_AWAY,
    AlarmState.ARMED_NIGHT,
    AlarmState.ARMED_VACATION,
}


def validate_user_code(*, user, raw_code: str) -> UserCode:
    """
    Validate a user code, translating accounts-layer exceptions into alarm-layer exceptions.
    """
    now = timezone.now()
    try:
        result = code_validation.validate_user_code(user=user, raw_code=raw_code, now=now)
    except code_validation.CodeRequiredError as exc:
        raise CodeRequiredError(str(exc)) from exc
    except code_validation.InvalidCodeError as exc:
        raise InvalidCodeError(str(exc)) from exc
    return result.code


def arm_alarm(*, user, target_state: str, raw_code):
    """Arm the alarm, validating a code when required by settings or provided by the caller."""
    if target_state not in ALLOWED_ARM_TARGET_STATES:
        raise InvalidTargetState("Invalid target_state.")

    profile = get_active_settings_profile()
    code_obj = None
    if get_setting_bool(profile, "code_arm_required") or raw_code is not None:
        _reject_if_locked_out(user=user, action="arm", metadata={"target_state": target_state})
        _reject_if_rate_limited(user=user)
        if not raw_code:
            record_failed_code(
                user=user,
                action="arm",
                metadata={"target_state": target_state, "reason": "missing"},
            )
            code_attempt_guard.register_failed_attempt()
            raise CodeRequired("Code is required to arm.")
        try:
            code_obj = validate_user_code(user=user, raw_code=raw_code)
        except InvalidCodeError as exc:
            record_failed_code(
                user=user,
                action="arm",
                metadata={"target_state": target_state},
            )
            code_attempt_guard.register_failed_attempt()
            raise InvalidCode(str(exc) or "Invalid code.") from exc

    snapshot = arm(target_state=target_state, user=user, code=code_obj)
    if code_obj is not None:
        record_code_used(
            user=user,
            code=code_obj,
            action="arm",
            metadata={"target_state": target_state},
        )
        code_attempt_guard.reset_lockout()
    return snapshot


def disarm_alarm(*, user, raw_code):
    """Disarm the alarm, requiring and validating a code."""
    _reject_if_locked_out(user=user, action="disarm")
    _reject_if_rate_limited(user=user)

    if not raw_code:
        record_failed_code(
            user=user,
            action="disarm",
            metadata={"reason": "missing"},
        )
        code_attempt_guard.register_failed_attempt()
        raise CodeRequired("Code is required to disarm.")
    try:
        code_obj = validate_user_code(user=user, raw_code=raw_code)
    except InvalidCodeError as exc:
        record_failed_code(user=user, action="disarm")
        code_attempt_guard.register_failed_attempt()
        raise InvalidCode(str(exc) or "Invalid code.") from exc

    snapshot = disarm(user=user, code=code_obj)
    record_code_used(user=user, code=code_obj, action="disarm")
    code_attempt_guard.reset_lockout()
    return snapshot
