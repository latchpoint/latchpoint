from __future__ import annotations

from django.db import models
from django.utils import timezone

from accounts.models import UserCode
from alarm.models import AlarmEvent, AlarmEventType, AlarmState, AlarmStateSnapshot, Sensor

from .constants import ARMED_STATES


def _event_type_for_state(state: str) -> str:
    """Map a state string to the correct `AlarmEventType`."""
    if state == AlarmState.DISARMED:
        return AlarmEventType.DISARMED
    if state in ARMED_STATES:
        return AlarmEventType.ARMED
    if state == AlarmState.PENDING:
        return AlarmEventType.PENDING
    if state == AlarmState.TRIGGERED:
        return AlarmEventType.TRIGGERED
    return AlarmEventType.STATE_CHANGED


def record_state_event(
    *,
    snapshot: AlarmStateSnapshot,
    state_from: str | None,
    state_to: str,
    user=None,
    code=None,
    sensor: Sensor | None = None,
    metadata: dict | None = None,
    timestamp=None,
) -> AlarmEvent:
    """Create an `AlarmEvent` capturing a state transition (armed/pending/triggered/etc)."""
    return AlarmEvent.objects.create(
        event_type=_event_type_for_state(state_to),
        state_from=state_from,
        state_to=state_to,
        timestamp=timestamp or timezone.now(),
        user=user,
        code=code,
        sensor=sensor,
        metadata=metadata or {},
    )


def record_sensor_event(sensor: Sensor, timestamp=None) -> AlarmEvent:
    """Create an `AlarmEvent` capturing that a sensor was triggered."""
    return AlarmEvent.objects.create(
        event_type=AlarmEventType.SENSOR_TRIGGERED,
        state_from=None,
        state_to=None,
        timestamp=timestamp or timezone.now(),
        sensor=sensor,
        metadata={"is_entry_point": sensor.is_entry_point},
    )


def record_failed_code(*, user, action: str, metadata: dict | None = None, timestamp=None) -> AlarmEvent:
    """Create an `AlarmEvent` capturing a failed code attempt."""
    return AlarmEvent.objects.create(
        event_type=AlarmEventType.FAILED_CODE,
        state_from=None,
        state_to=None,
        timestamp=timestamp or timezone.now(),
        user=user,
        code=None,
        sensor=None,
        metadata={"action": action, **(metadata or {})},
    )


def record_code_used(*, user, code: UserCode, action: str, metadata: dict | None = None, timestamp=None) -> AlarmEvent:
    """Increment code usage counters and create an `AlarmEvent` capturing code usage."""
    now = timestamp or timezone.now()
    UserCode.objects.filter(id=code.id).update(
        uses_count=models.F("uses_count") + 1,
        last_used_at=now,
    )
    return AlarmEvent.objects.create(
        event_type=AlarmEventType.CODE_USED,
        state_from=None,
        state_to=None,
        timestamp=now,
        user=user,
        code=code,
        sensor=None,
        metadata={"action": action, **(metadata or {})},
    )
