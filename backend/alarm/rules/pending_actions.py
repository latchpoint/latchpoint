"""Helpers for the PendingAction queue (ADR-0091).

The queue defers rule actions whose ``delay_seconds`` is > 0. A scheduler
task fires due rows; this module owns enqueue + cancellation primitives.
"""

from __future__ import annotations

import copy
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from alarm.models import (
    AlarmState,
    PendingAction,
    PendingActionCancelReason,
    PendingActionStatus,
    Rule,
)
from alarm.state_machine.constants import ARMED_STATES

if TYPE_CHECKING:
    from alarm.rules.action_handlers import ActionContext

logger = logging.getLogger(__name__)


def enqueue_pending_action(
    *,
    rule: Rule,
    action_index: int,
    action_payload: dict,
    delay_seconds: int,
    ctx: "ActionContext",
) -> PendingAction:
    """Persist a deferred action row.

    The caller has already checked ``delay_seconds > 0``. ``armed_state_at_schedule``
    is captured here so disarm-cancellation can target only rows scheduled while
    the alarm was armed (and leave alone any rows scheduled while disarmed —
    e.g., a rule that runs in disarmed state).
    """
    snapshot = ctx.alarm_services.get_current_snapshot(process_timers=True)
    armed_state = snapshot.current_state if snapshot is not None else AlarmState.DISARMED

    now = timezone.now()
    fire_at = now + timedelta(seconds=delay_seconds)

    return PendingAction.objects.create(
        rule=rule,
        action_index=action_index,
        action_payload=copy.deepcopy(action_payload),
        delay_seconds=delay_seconds,
        fire_at=fire_at,
        status=PendingActionStatus.SCHEDULED,
        armed_state_at_schedule=armed_state,
        actor_user=ctx.actor_user if not isinstance(ctx.actor_user, str) else None,
    )


def cancel_pending_actions(
    *,
    queryset,
    reason: str,
) -> int:
    """Atomically flip a queryset of PendingActions to ``cancelled``.

    Returns the count of rows actually transitioned (idempotent against rows
    already in a terminal state). The queryset is filtered to ``status=scheduled``
    inside the transaction so concurrent fires don't race.
    """
    with transaction.atomic():
        affected = queryset.filter(status=PendingActionStatus.SCHEDULED).update(
            status=PendingActionStatus.CANCELLED,
            cancel_reason=reason,
            updated_at=timezone.now(),
        )
    if affected:
        logger.info("Cancelled %d pending actions (reason=%s)", affected, reason)
    return affected


def cancel_for_disarm() -> int:
    """Cancel every pending action that was scheduled while the alarm was armed.

    Intended to be called from a signal receiver when the alarm transitions
    to DISARMED. Rows scheduled while DISARMED are left alone (a rule that
    fires in disarmed state — e.g., a "log disarm event" rule — shouldn't
    be cancelled by the very disarm that scheduled it).
    """
    qs = PendingAction.objects.filter(
        status=PendingActionStatus.SCHEDULED,
        armed_state_at_schedule__in=list(ARMED_STATES),
    )
    return cancel_pending_actions(queryset=qs, reason=PendingActionCancelReason.DISARM)


def cancel_for_rule(rule_id: int, *, reason: str = PendingActionCancelReason.RULE_DELETED) -> int:
    """Cancel all scheduled pending actions for a given rule."""
    qs = PendingAction.objects.filter(rule_id=rule_id, status=PendingActionStatus.SCHEDULED)
    return cancel_pending_actions(queryset=qs, reason=reason)


def cancel_by_id(pending_action_id: int) -> bool:
    """Manual cancel via the API. Returns True if a row was transitioned."""
    qs = PendingAction.objects.filter(id=pending_action_id)
    return cancel_pending_actions(queryset=qs, reason=PendingActionCancelReason.MANUAL) > 0
