from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth.hashers import check_password
from django.utils import timezone as django_timezone

from accounts.models import User
from config.domain_exceptions import ValidationError
from locks.models import DoorCode, DoorCodeEvent


class CodeValidationError(ValidationError):
    pass


class CodeRequiredError(CodeValidationError):
    pass


class InvalidCodeError(CodeValidationError):
    pass


class CodeExpiredError(CodeValidationError):
    pass


class CodeExhaustedError(CodeValidationError):
    pass


@dataclass(frozen=True)
class DoorCodeValidationResult:
    code: DoorCode


def validate_door_code(
    *,
    user: User,
    raw_code: str,
    lock_entity_id: str | None = None,
    now: datetime | None = None,
) -> DoorCodeValidationResult:
    """Validate a door code for a user, optionally constrained to a specific lock."""
    if now is None:
        now = django_timezone.now()

    if raw_code is None:
        raise CodeRequiredError("Code is required.")

    raw_code = str(raw_code).strip()
    if len(raw_code) < 4 or len(raw_code) > 8:
        raise InvalidCodeError("Invalid code.")

    candidates = DoorCode.objects.filter(user=user, is_active=True)
    if lock_entity_id:
        candidates = candidates.filter(lock_assignments__lock_entity_id=lock_entity_id)

    for candidate in candidates:
        if check_password(raw_code, candidate.code_hash):
            if candidate.max_uses is not None and candidate.uses_count >= candidate.max_uses:
                raise CodeExhaustedError("Code has reached maximum uses.")

            if candidate.code_type in (
                DoorCode.CodeType.TEMPORARY,
                DoorCode.CodeType.ONE_TIME,
            ):
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
                    raise CodeExpiredError("Code has expired.")

            return DoorCodeValidationResult(code=candidate)

    raise InvalidCodeError("Invalid code.")


def record_door_code_usage(
    *,
    code: DoorCode,
    lock_entity_id: str | None = None,
    success: bool = True,
) -> None:
    """Record door code usage (and optionally deactivate one-time codes), emitting an event."""
    now = django_timezone.now()

    if success:
        code.uses_count += 1
        code.last_used_at = now
        if lock_entity_id:
            code.last_used_lock = lock_entity_id
        code.save(update_fields=["uses_count", "last_used_at", "last_used_lock", "updated_at"])

        if code.code_type == DoorCode.CodeType.ONE_TIME:
            code.is_active = False
            code.save(update_fields=["is_active", "updated_at"])

    DoorCodeEvent.objects.create(
        door_code=code,
        lock_entity_id=lock_entity_id or "",
        event_type=DoorCodeEvent.EventType.CODE_USED if success else DoorCodeEvent.EventType.CODE_FAILED,
        metadata={
            "success": success,
            "uses_count": code.uses_count,
        },
    )
