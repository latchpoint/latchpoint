from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from alarm.models import AlarmState, AlarmStateSnapshot, Sensor

from .constants import ARMED_STATES
from .errors import TransitionError
from .events import record_sensor_event
from .settings import get_active_settings_profile
from .snapshot_store import get_snapshot_for_update, set_previous_armed_state, transition
from .timing import resolve_timing, timing_from_snapshot
from .settings import get_setting_bool


@transaction.atomic
def arm(
    *,
    target_state: str,
    user=None,
    code=None,
    reason: str = "arm",
    metadata: dict | None = None,
) -> AlarmStateSnapshot:
    """Transition from disarmed -> arming/armed depending on configured arming time."""
    if target_state not in ARMED_STATES:
        raise TransitionError("Target state must be an armed state.")
    profile = get_active_settings_profile()
    snapshot = get_snapshot_for_update()
    if snapshot.current_state != AlarmState.DISARMED:
        raise TransitionError("Alarm can only be armed from disarmed state.")

    timing = resolve_timing(profile, target_state)
    now = timezone.now()
    snapshot.settings_profile = profile
    snapshot.target_armed_state = target_state
    snapshot.timing_snapshot = timing.as_dict()
    snapshot.save(update_fields=["settings_profile", "target_armed_state", "timing_snapshot"])

    if timing.arming_time <= 0:
        return transition(
            snapshot=snapshot,
            state_to=target_state,
            now=now,
            user=user,
            code=code,
            reason=reason,
            metadata=metadata,
            exit_at=None,
        )

    exit_at = now + timedelta(seconds=timing.arming_time)
    return transition(
        snapshot=snapshot,
        state_to=AlarmState.ARMING,
        now=now,
        user=user,
        code=code,
        reason=reason,
        metadata=metadata,
        exit_at=exit_at,
    )


@transaction.atomic
def cancel_arming(*, user=None, code=None, reason: str = "cancel_arming", metadata: dict | None = None) -> AlarmStateSnapshot:
    """Cancel an in-progress arming transition and return to disarmed."""
    snapshot = get_snapshot_for_update()
    if snapshot.current_state != AlarmState.ARMING:
        raise TransitionError("Alarm is not currently arming.")
    now = timezone.now()
    snapshot.target_armed_state = None
    snapshot.timing_snapshot = {}
    snapshot.save(update_fields=["target_armed_state", "timing_snapshot"])
    return transition(
        snapshot=snapshot,
        state_to=AlarmState.DISARMED,
        now=now,
        user=user,
        code=code,
        reason=reason,
        metadata=metadata,
    )


@transaction.atomic
def disarm(*, user=None, code=None, reason: str = "disarm", metadata: dict | None = None) -> AlarmStateSnapshot:
    """Transition to disarmed and clear any pending target/timing state."""
    snapshot = get_snapshot_for_update()
    if snapshot.current_state == AlarmState.DISARMED:
        return snapshot
    now = timezone.now()
    snapshot.target_armed_state = None
    snapshot.timing_snapshot = {}
    snapshot.save(update_fields=["target_armed_state", "timing_snapshot"])
    return transition(
        snapshot=snapshot,
        state_to=AlarmState.DISARMED,
        now=now,
        user=user,
        code=code,
        reason=reason,
        metadata=metadata,
    )


@transaction.atomic
def sensor_triggered(*, sensor: Sensor, user=None, reason: str = "sensor_triggered") -> AlarmStateSnapshot:
    """Handle a sensor trigger, transitioning to pending/triggered depending on entry-point behavior."""
    snapshot = get_snapshot_for_update()
    now = timezone.now()
    record_sensor_event(sensor, timestamp=now)

    if snapshot.current_state in {AlarmState.PENDING, AlarmState.TRIGGERED}:
        return snapshot

    if snapshot.current_state not in ARMED_STATES and snapshot.current_state != AlarmState.ARMING:
        return snapshot

    set_previous_armed_state(snapshot)
    snapshot.save(update_fields=["previous_state"])

    timing = timing_from_snapshot(snapshot)

    if sensor.is_entry_point:
        snapshot.timing_snapshot = timing.as_dict()
        snapshot.save(update_fields=["timing_snapshot"])
        exit_at = now + timedelta(seconds=timing.delay_time)
        return transition(
            snapshot=snapshot,
            state_to=AlarmState.PENDING,
            now=now,
            user=user,
            reason=reason,
            exit_at=exit_at,
            update_previous=False,
            sensor=sensor,
        )

    exit_at = now + timedelta(seconds=timing.trigger_time)
    return transition(
        snapshot=snapshot,
        state_to=AlarmState.TRIGGERED,
        now=now,
        user=user,
        reason=reason,
        exit_at=exit_at,
        update_previous=False,
        sensor=sensor,
    )


@transaction.atomic
def timer_expired(*, reason: str = "timer_expired") -> AlarmStateSnapshot:
    """Advance timer-based transitions (arming->armed, pending->triggered, triggered->return/disarm)."""
    snapshot = get_snapshot_for_update()
    if not snapshot.exit_at:
        return snapshot
    now = timezone.now()
    if snapshot.exit_at > now:
        return snapshot

    timing = timing_from_snapshot(snapshot)

    if snapshot.current_state == AlarmState.ARMING:
        target_state = snapshot.target_armed_state
        if target_state not in ARMED_STATES:
            raise TransitionError("Missing target armed state for arming timer.")
        snapshot.exit_at = None
        snapshot.save(update_fields=["exit_at"])
        return transition(
            snapshot=snapshot,
            state_to=target_state,
            now=now,
            reason=reason,
            exit_at=None,
        )

    if snapshot.current_state == AlarmState.PENDING:
        exit_at = now + timedelta(seconds=timing.trigger_time)
        return transition(
            snapshot=snapshot,
            state_to=AlarmState.TRIGGERED,
            now=now,
            reason=reason,
            exit_at=exit_at,
            update_previous=False,
        )

    if snapshot.current_state == AlarmState.TRIGGERED:
        snapshot.exit_at = None
        snapshot.save(update_fields=["exit_at"])
        if get_setting_bool(snapshot.settings_profile, "disarm_after_trigger"):
            snapshot.target_armed_state = None
            snapshot.timing_snapshot = {}
            snapshot.save(update_fields=["target_armed_state", "timing_snapshot"])
            return transition(
                snapshot=snapshot,
                state_to=AlarmState.DISARMED,
                now=now,
                reason=reason,
            )
        return_state = snapshot.previous_state if snapshot.previous_state in ARMED_STATES else AlarmState.DISARMED
        return transition(
            snapshot=snapshot,
            state_to=return_state,
            now=now,
            reason=reason,
        )

    return snapshot


def get_current_snapshot(*, process_timers: bool = True) -> AlarmStateSnapshot:
    """Return the current alarm snapshot, optionally processing due timers first."""
    if process_timers:
        return timer_expired(reason="read_state")
    with transaction.atomic():
        return get_snapshot_for_update()


@transaction.atomic
def trigger(*, user=None, reason: str = "trigger") -> AlarmStateSnapshot:
    """Force a transition to triggered from any armed state."""
    snapshot = get_snapshot_for_update()
    now = timezone.now()
    if snapshot.current_state == AlarmState.TRIGGERED:
        return snapshot
    if snapshot.current_state == AlarmState.DISARMED:
        raise TransitionError("Cannot trigger alarm while disarmed.")

    set_previous_armed_state(snapshot)
    snapshot.save(update_fields=["previous_state"])

    timing = timing_from_snapshot(snapshot)

    exit_at = now + timedelta(seconds=timing.trigger_time)
    return transition(
        snapshot=snapshot,
        state_to=AlarmState.TRIGGERED,
        now=now,
        user=user,
        reason=reason,
        exit_at=exit_at,
        update_previous=False,
    )
