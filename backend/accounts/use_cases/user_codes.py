from __future__ import annotations

from django.contrib.auth.hashers import make_password

from accounts.models import User, UserCode, UserCodeAllowedState


DEFAULT_CODE_ALLOWED_STATES = [
    UserCodeAllowedState.AlarmState.ARMED_HOME,
    UserCodeAllowedState.AlarmState.ARMED_AWAY,
    UserCodeAllowedState.AlarmState.ARMED_NIGHT,
    UserCodeAllowedState.AlarmState.ARMED_VACATION,
    UserCodeAllowedState.AlarmState.ARMED_CUSTOM_BYPASS,
]


def create_user_code(
    *,
    user: User,
    raw_code: str,
    label: str = "",
    code_type: str = UserCode.CodeType.PERMANENT,
    start_at=None,
    end_at=None,
    days_of_week: int | None = None,
    window_start=None,
    window_end=None,
    allowed_states: list[str] | None = None,
) -> UserCode:
    """Create a user code and its allowed states."""
    raw_code = (raw_code or "").strip()
    code = UserCode.objects.create(
        user=user,
        code_hash=make_password(raw_code),
        label=label or "",
        code_type=code_type,
        pin_length=len(raw_code),
        is_active=True,
        start_at=start_at,
        end_at=end_at,
        days_of_week=days_of_week,
        window_start=window_start,
        window_end=window_end,
    )
    selected_states = allowed_states or DEFAULT_CODE_ALLOWED_STATES
    UserCodeAllowedState.objects.bulk_create(
        [UserCodeAllowedState(code=code, state=state) for state in selected_states],
        ignore_conflicts=True,
    )
    return code


def update_user_code(
    *,
    code: UserCode,
    changes: dict,
) -> UserCode:
    """Update a user code and its allowed states."""
    if "code" in changes and changes.get("code"):
        raw_code = str(changes.get("code") or "").strip()
        code.code_hash = make_password(raw_code)
        code.pin_length = len(raw_code)

    if "label" in changes:
        code.label = changes.get("label") or ""
    if "is_active" in changes:
        code.is_active = bool(changes.get("is_active"))

    time_keys = {"start_at", "end_at", "days_of_week", "window_start", "window_end"}
    if any(key in changes for key in time_keys):
        if "start_at" in changes:
            code.start_at = changes.get("start_at")
        if "end_at" in changes:
            code.end_at = changes.get("end_at")
        if "days_of_week" in changes:
            code.days_of_week = changes.get("days_of_week")
        if "window_start" in changes:
            code.window_start = changes.get("window_start")
        if "window_end" in changes:
            code.window_end = changes.get("window_end")
    code.save()

    if "allowed_states" in changes:
        allowed_states = changes.get("allowed_states") or []
        code.allowed_states.all().delete()
        UserCodeAllowedState.objects.bulk_create(
            [UserCodeAllowedState(code=code, state=state) for state in allowed_states],
            ignore_conflicts=True,
        )

    return code
