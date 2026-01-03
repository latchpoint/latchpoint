from __future__ import annotations

"""
Compatibility facade for alarm domain operations.

Historical entrypoint used by views, rules engine, and tests.
New code should prefer use-cases or the `alarm.state_machine` modules directly.
"""

from django.utils import timezone

from accounts.models import UserCode
from accounts.use_cases import code_validation

from .state_machine.constants import ARMED_STATES
from .state_machine.errors import CodeRequiredError, InvalidCodeError, TransitionError
from .state_machine.events import record_code_used, record_failed_code
from .state_machine.settings import get_active_settings_profile
from .state_machine.transitions import (
    arm,
    cancel_arming,
    disarm,
    get_current_snapshot,
    sensor_triggered,
    timer_expired,
    trigger,
)


def validate_user_code(*, user, raw_code: str) -> UserCode:
    """
    Compatibility wrapper around `accounts.use_cases.code_validation.validate_user_code`.

    Kept here so existing call sites and tests that patch `alarm.services.timezone.now`
    remain stable.
    """

    now = timezone.now()
    try:
        result = code_validation.validate_user_code(user=user, raw_code=raw_code, now=now)
    except code_validation.CodeRequiredError as exc:
        raise CodeRequiredError(str(exc)) from exc
    except code_validation.InvalidCodeError as exc:
        raise InvalidCodeError(str(exc)) from exc
    return result.code

