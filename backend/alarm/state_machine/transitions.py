from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from alarm.models import AlarmState, AlarmStateSnapshot

from .constants import ARMED_STATES
from .errors import TransitionError
from .settings import get_active_settings_profile
from .snapshot_store import get_snapshot_for_update, set_previous_armed_state, transition


@transaction.atomic
def arm(
    *,
    target_state: str,
    arming_time_seconds: int | None = None,
    user=None,
    code=None,
    reason: str = "arm",
    metadata: dict | None = None,
) -> AlarmStateSnapshot:
    """Transition from disarmed -> arming/armed.

    When ``arming_time_seconds`` > 0, enters ARMING with an ``exit_at`` timer
    that advances to ``target_state`` when expired. When 0 or ``None``, the
    transition skips ARMING and goes directly to ``target_state`` (ADR-0095).
    """
    if target_state not in ARMED_STATES:
        raise TransitionError("Target state must be an armed state.")
    profile = get_active_settings_profile()
    snapshot = get_snapshot_for_update()
    if snapshot.current_state != AlarmState.DISARMED:
        raise TransitionError("Alarm can only be armed from disarmed state.")

    now = timezone.now()
    snapshot.settings_profile = profile
    snapshot.target_armed_state = target_state
    snapshot.save(update_fields=["settings_profile", "target_armed_state"])

    arming_seconds = int(arming_time_seconds) if arming_time_seconds else 0
    if arming_seconds <= 0:
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

    exit_at = now + timedelta(seconds=arming_seconds)
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
def cancel_arming(
    *, user=None, code=None, reason: str = "cancel_arming", metadata: dict | None = None
) -> AlarmStateSnapshot:
    """Cancel an in-progress arming transition and return to disarmed."""
    snapshot = get_snapshot_for_update()
    if snapshot.current_state != AlarmState.ARMING:
        raise TransitionError("Alarm is not currently arming.")
    now = timezone.now()
    snapshot.target_armed_state = None
    snapshot.save(update_fields=["target_armed_state"])
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
    """Transition to disarmed and clear any pending target state."""
    snapshot = get_snapshot_for_update()
    if snapshot.current_state == AlarmState.DISARMED:
        return snapshot
    now = timezone.now()
    snapshot.target_armed_state = None
    snapshot.save(update_fields=["target_armed_state"])
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
def timer_expired(*, reason: str = "timer_expired") -> AlarmStateSnapshot:
    """Advance timer-based transitions.

    - ARMING -> ARMED_* when the exit-delay timer expires.
    - PENDING -> TRIGGERED when an explicit ``exit_at`` (e.g. from
      ``set_state(pending, exit_at=...)`` or a delayed ``alarm_set_state``
      action) expires.
    - TRIGGERED -> previous_armed_state or DISARMED when an explicit
      ``exit_at`` expires.
    """
    snapshot = get_snapshot_for_update()
    if not snapshot.exit_at:
        return snapshot
    now = timezone.now()
    if snapshot.exit_at > now:
        return snapshot

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
        return transition(
            snapshot=snapshot,
            state_to=AlarmState.TRIGGERED,
            now=now,
            reason=reason,
            exit_at=None,
            update_previous=False,
        )

    if snapshot.current_state == AlarmState.TRIGGERED:
        snapshot.exit_at = None
        snapshot.save(update_fields=["exit_at"])
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
    """Force a transition to triggered from any armed/pending state."""
    snapshot = get_snapshot_for_update()
    now = timezone.now()
    if snapshot.current_state == AlarmState.TRIGGERED:
        return snapshot
    if snapshot.current_state == AlarmState.DISARMED:
        raise TransitionError("Cannot trigger alarm while disarmed.")

    set_previous_armed_state(snapshot)
    snapshot.save(update_fields=["previous_state"])

    return transition(
        snapshot=snapshot,
        state_to=AlarmState.TRIGGERED,
        now=now,
        user=user,
        reason=reason,
        exit_at=None,
        update_previous=False,
    )


@transaction.atomic
def set_state(
    *,
    new_state: str,
    user=None,
    reason: str = "set_state",
    exit_at=None,
    metadata: dict | None = None,
) -> AlarmStateSnapshot:
    """Set the alarm state directly (ADR-0094 composable primitive).

    Guards (per ADR-0094 §3.2):

    - ``ARMING`` is rejected — the arming flow needs ``target_armed_state``
      setup that single-shot setters can't provide. Use ``arm()`` instead.
    - ``DISARMED`` delegates to ``disarm()`` for proper cleanup of
      ``target_armed_state``.
    - ``PENDING`` does not auto-advance unless an explicit ``exit_at`` is
      supplied. Manual PENDING is informational; compose with a delayed
      ``alarm_trigger`` for entry-delay flows.
    - Idempotent: a no-op when ``current_state == new_state``.
    """
    if new_state == AlarmState.ARMING:
        raise TransitionError("Use arm() — ARMING requires target_armed_state setup")
    if new_state not in {
        AlarmState.DISARMED,
        AlarmState.PENDING,
        AlarmState.TRIGGERED,
        *ARMED_STATES,
    }:
        raise TransitionError(f"Unknown alarm state: {new_state}")

    if new_state == AlarmState.DISARMED:
        return disarm(user=user, reason=reason, metadata=metadata)

    snapshot = get_snapshot_for_update()
    if snapshot.current_state == new_state:
        return snapshot

    now = timezone.now()

    if new_state in ARMED_STATES:
        profile = get_active_settings_profile()
        snapshot.settings_profile = profile
        snapshot.target_armed_state = None
        snapshot.save(update_fields=["settings_profile", "target_armed_state"])

    set_previous_armed_state(snapshot)
    snapshot.save(update_fields=["previous_state"])

    return transition(
        snapshot=snapshot,
        state_to=new_state,
        now=now,
        user=user,
        reason=reason,
        exit_at=exit_at,
        update_previous=False,
        metadata=metadata,
    )
