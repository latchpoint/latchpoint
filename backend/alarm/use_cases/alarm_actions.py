from __future__ import annotations

from alarm import services
from alarm.models import AlarmState
from alarm.state_machine.settings import get_setting_bool
from config.domain_exceptions import DomainError, UnauthorizedError, ValidationError


class AlarmActionError(DomainError):
    pass


class InvalidTargetState(ValidationError):
    pass


class CodeRequired(ValidationError):
    pass


class InvalidCode(UnauthorizedError):
    pass


ALLOWED_ARM_TARGET_STATES = {
    AlarmState.ARMED_HOME,
    AlarmState.ARMED_AWAY,
    AlarmState.ARMED_NIGHT,
    AlarmState.ARMED_VACATION,
}


def arm_alarm(*, user, target_state: str, raw_code):
    """Arm the alarm, validating a code when required by settings or provided by the caller."""
    if target_state not in ALLOWED_ARM_TARGET_STATES:
        raise InvalidTargetState("Invalid target_state.")

    profile = services.get_active_settings_profile()
    code_obj = None
    if get_setting_bool(profile, "code_arm_required") or raw_code is not None:
        if not raw_code:
            services.record_failed_code(
                user=user,
                action="arm",
                metadata={"target_state": target_state, "reason": "missing"},
            )
            raise CodeRequired("Code is required to arm.")
        try:
            code_obj = services.validate_user_code(user=user, raw_code=raw_code)
        except services.InvalidCodeError as exc:
            services.record_failed_code(
                user=user,
                action="arm",
                metadata={"target_state": target_state},
            )
            raise InvalidCode(str(exc) or "Invalid code.") from exc

    snapshot = services.arm(target_state=target_state, user=user, code=code_obj)
    if code_obj is not None:
        services.record_code_used(
            user=user,
            code=code_obj,
            action="arm",
            metadata={"target_state": target_state},
        )
    return snapshot


def disarm_alarm(*, user, raw_code):
    """Disarm the alarm, requiring and validating a code."""
    if not raw_code:
        services.record_failed_code(
            user=user,
            action="disarm",
            metadata={"reason": "missing"},
        )
        raise CodeRequired("Code is required to disarm.")
    try:
        code_obj = services.validate_user_code(user=user, raw_code=raw_code)
    except services.InvalidCodeError as exc:
        services.record_failed_code(user=user, action="disarm")
        raise InvalidCode(str(exc) or "Invalid code.") from exc

    snapshot = services.disarm(user=user, code=code_obj)
    services.record_code_used(user=user, code=code_obj, action="disarm")
    return snapshot
