"""Background tasks for the alarm app."""

from __future__ import annotations

import copy
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from alarm.models import (
    AlarmEvent,
    Entity,
    PendingAction,
    PendingActionCancelReason,
    PendingActionStatus,
    RuleActionLog,
    RuleEntityRef,
)
from alarm.system_config_utils import get_int_system_config_value
from scheduler import DailyAt, Every, register

logger = logging.getLogger(__name__)

# How far past fire_at a PendingAction can be before it's auto-cancelled.
# Catches "backend was down for hours, don't fire stale notifications" (ADR-0091).
PENDING_ACTION_STALE_THRESHOLD_SECONDS = 60


def _is_home_assistant_active() -> bool:
    """
    Return True if Home Assistant is enabled and minimally configured.

    Must not perform network IO (scheduler gating predicate).
    """
    try:
        from integrations_home_assistant.connection import (
            get_cached_connection,
            warm_up_cached_connection_if_needed,
        )

        cached = get_cached_connection()
        if cached is None:
            warm_up_cached_connection_if_needed()
            cached = get_cached_connection()
        if cached is None:
            return False
        if cached.error:
            return False
        return bool(cached.enabled and cached.base_url and cached.token)
    except Exception:
        return False


def _get_retention_days() -> int:
    """Read events.retention_days from SystemConfig, fallback to default."""
    return get_int_system_config_value(key="events.retention_days")


@register(
    "cleanup_old_events",
    schedule=DailyAt(hour=3, minute=0),
    description="Deletes old alarm history entries based on your retention settings.",
)
def cleanup_old_events() -> int:
    """
    Delete AlarmEvent records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_retention_days()
    if retention_days <= 0:
        return 0
    cutoff = timezone.now() - timedelta(days=retention_days)

    deleted_count, _ = AlarmEvent.objects.filter(timestamp__lt=cutoff).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d events older than %d days (cutoff: %s)",
            deleted_count,
            retention_days,
            cutoff.isoformat(),
        )

    return deleted_count


def _get_rule_log_retention_days() -> int:
    """Read rule_logs.retention_days from SystemConfig, fallback to default."""
    return get_int_system_config_value(key="rule_logs.retention_days")


@register(
    "cleanup_rule_action_logs",
    schedule=DailyAt(hour=3, minute=30),
    description="Deletes old rule activity logs based on your retention settings.",
)
def cleanup_rule_action_logs() -> int:
    """
    Delete RuleActionLog records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_rule_log_retention_days()
    if retention_days <= 0:
        return 0
    cutoff = timezone.now() - timedelta(days=retention_days)

    deleted_count, _ = RuleActionLog.objects.filter(fired_at__lt=cutoff).delete()

    if deleted_count > 0:
        logger.info(
            "Cleaned up %d rule action logs older than %d days (cutoff: %s)",
            deleted_count,
            retention_days,
            cutoff.isoformat(),
        )

    return deleted_count


@register(
    "cleanup_expired_sessions",
    schedule=DailyAt(hour=4, minute=0),
    description="Removes expired login sessions to keep things running smoothly.",
)
def cleanup_expired_sessions() -> int:
    """
    Delete expired Django sessions from the database.

    Wraps Django's clearsessions management command.
    Returns the count of expired sessions at the time of cleanup.
    """
    from django.contrib.sessions.models import Session
    from django.core.management import call_command

    expired_count = Session.objects.filter(expire_date__lt=timezone.now()).count()

    if expired_count == 0:
        logger.debug("No expired sessions to clean up")
        return 0

    call_command("clearsessions", verbosity=0)
    logger.info("Cleaned up %d expired sessions", expired_count)
    return expired_count


def _get_entity_sync_interval() -> int:
    """Read entity_sync.interval_seconds from SystemConfig, fallback to default."""
    return get_int_system_config_value(key="entity_sync.interval_seconds")


@register(
    "sync_entity_states",
    schedule=Every(seconds=300, jitter=30),
    description="Refreshes device states from Home Assistant when available.",
    enabled_when=_is_home_assistant_active,
)
def sync_entity_states() -> dict:
    """
    Refresh entity states from Home Assistant.

    Returns dict with counts: {"synced": N, "updated": N, "errors": N}
    """
    from alarm.gateways.home_assistant import (
        HomeAssistantNotConfigured,
        HomeAssistantNotReachable,
        default_home_assistant_gateway,
    )
    from alarm.websocket import broadcast_entity_sync

    interval = _get_entity_sync_interval()
    if interval <= 0:
        logger.debug("Entity sync disabled (interval=%d)", interval)
        return {"synced": 0, "updated": 0, "errors": 0, "disabled": True}

    try:
        default_home_assistant_gateway.ensure_available()
    except (HomeAssistantNotConfigured, HomeAssistantNotReachable) as e:
        logger.debug("Skipping entity sync: Home Assistant unavailable (%s)", e)
        return {"synced": 0, "updated": 0, "errors": 0, "skipped": True}

    try:
        ha_entities = default_home_assistant_gateway.list_entities()
    except Exception as e:
        logger.warning("Entity sync failed to fetch from Home Assistant: %s", e)
        return {"synced": 0, "updated": 0, "errors": 1}

    ha_states = {e["entity_id"]: e for e in ha_entities}
    now = timezone.now()
    updated = 0
    synced = 0
    changed_entities = []

    for entity in Entity.objects.filter(source="home_assistant"):
        ha_data = ha_states.get(entity.entity_id)
        if not ha_data:
            continue

        new_state = ha_data.get("state")
        update_fields = ["last_seen"]

        if entity.last_state != new_state:
            old_state = entity.last_state
            logger.info(
                "Entity %s state changed: %s -> %s (detected via sync)",
                entity.entity_id,
                old_state,
                new_state,
            )
            entity.last_state = new_state
            entity.last_changed = now
            update_fields.extend(["last_state", "last_changed"])
            updated += 1
            changed_entities.append(
                {
                    "entity_id": entity.entity_id,
                    "old_state": old_state,
                    "new_state": new_state,
                }
            )

        entity.last_seen = now
        entity.save(update_fields=update_fields)
        synced += 1

    if updated > 0:
        logger.info("Entity sync: updated %d entities with changed states", updated)
        broadcast_entity_sync(entities=changed_entities)

        # Notify dispatcher of changed entities (ADR 0057)
        try:
            from alarm.dispatcher import notify_entities_changed

            changed_entity_ids = [e["entity_id"] for e in changed_entities]
            notify_entities_changed(source="home_assistant", entity_ids=changed_entity_ids, changed_at=now)
        except Exception as e:
            logger.debug("Dispatcher notification skipped: %s", e)

    return {"synced": synced, "updated": updated, "errors": 0}


@register(
    "broadcast_system_status",
    schedule=Every(seconds=2),
    description="Keeps the app up to date with the latest connection status of your integrations.",
)
def broadcast_system_status() -> None:
    """Broadcast integration status to websocket clients (local integrations)."""
    from alarm.system_status import recompute_and_broadcast_system_status

    recompute_and_broadcast_system_status(include_home_assistant=False)


@register(
    "check_home_assistant",
    schedule=Every(seconds=30, jitter=5),
    description="Checks whether Home Assistant is reachable, so the app can show an accurate status.",
    enabled_when=_is_home_assistant_active,
)
def check_home_assistant() -> None:
    """Check Home Assistant status and broadcast if changed."""
    from alarm.system_status import recompute_and_broadcast_system_status

    recompute_and_broadcast_system_status(include_home_assistant=True)


@register(
    "process_due_rule_runtimes",
    schedule=Every(seconds=5, jitter=1),
    description="Completes “wait for X seconds” rule timers and triggers any rules that become due.",
)
def process_due_rule_runtimes() -> dict:
    """
    Process rule runtimes with scheduled_for <= now.

    This ensures "for: N seconds" rules fire even without new integration events.
    Part of ADR 0057 implementation.

    Returns dict with counts: {"processed": N, "fired": N, "errors": N}
    """
    from alarm import rules_engine
    from alarm.models import RuleRuntimeState
    from alarm.rules.repositories import default_rule_engine_repositories

    now = timezone.now()

    # Check if any due runtimes exist (quick check to avoid full evaluation)
    due_count = RuleRuntimeState.objects.filter(
        scheduled_for__lte=now,
        status="satisfied",
    ).count()

    if due_count == 0:
        return {"processed": 0, "fired": 0, "errors": 0}

    # Run the rules engine to process due runtimes
    repos = default_rule_engine_repositories()
    try:
        result = rules_engine.run_rules(now=now, repos=repos)
        return {
            "processed": due_count,
            "fired": result.fired,
            "errors": result.errors,
        }
    except Exception as e:
        logger.exception("Failed to process due rule runtimes: %s", e)
        return {"processed": 0, "fired": 0, "errors": 1}


@register(
    "cleanup_orphan_rule_entity_refs",
    schedule=DailyAt(hour=4, minute=30),
    description="Cleans up stale rule references to devices that no longer exist.",
)
def cleanup_orphan_rule_entity_refs() -> int:
    """
    Remove RuleEntityRef rows pointing to non-existent entities.

    Daily cleanup for stale references as part of ADR 0057.

    Returns the count of deleted records.
    """
    # Find refs where entity no longer exists
    # Using a subquery approach that Django optimizes to avoid loading all IDs into memory
    orphan_refs = RuleEntityRef.objects.exclude(entity_id__in=Entity.objects.values("id"))

    count = orphan_refs.count()
    if count > 0:
        orphan_refs.delete()
        logger.info("Cleaned up %d orphan RuleEntityRef rows", count)

    return count


def _recover_alarm_from_stale_pending_action(stale_ids: list[int]) -> None:
    """Recover the alarm from a stuck PENDING after stale-cancelled alarm_trigger rows.

    ADR-0094 §3.6: if the backend was down past the stale threshold while the
    alarm was in PENDING with a queued trigger, the queued trigger has just
    been cancelled. The snapshot would otherwise sit in PENDING with no
    scheduled follow-up. Step the alarm back to its previous armed state.

    Best-effort: any failure is logged and swallowed so the scheduler tick
    keeps making progress.
    """
    try:
        from alarm.models import AlarmState
        from alarm.state_machine.constants import ARMED_STATES
        from alarm.state_machine.transitions import get_current_snapshot, set_state
    except Exception:
        logger.warning("stale-cancel recovery imports failed", exc_info=True)
        return

    try:
        snapshot = get_current_snapshot(process_timers=False)
    except Exception:
        logger.warning("stale-cancel recovery snapshot read failed", exc_info=True)
        return

    if snapshot.current_state != AlarmState.PENDING:
        return

    target = snapshot.previous_state if snapshot.previous_state in ARMED_STATES else AlarmState.DISARMED
    try:
        set_state(
            new_state=target,
            reason="pending_action_stale_recovery",
            metadata={"stale_pending_action_ids": stale_ids},
        )
        logger.info(
            "Recovered alarm from stale PENDING to %s (stale ids=%s)",
            target,
            stale_ids,
        )
    except Exception:
        logger.warning("stale-cancel recovery set_state failed", exc_info=True)


def _fire_one_pending_action(pa: PendingAction) -> None:
    """Dispatch a single pending action through the handler registry.

    Marks the row ``fired`` (or ``failed``) with the handler's result. Called
    from inside a per-row ``select_for_update`` block so concurrent ticks
    can't double-fire.
    """
    from alarm.gateways.home_assistant import default_home_assistant_gateway
    from alarm.gateways.zigbee2mqtt import default_zigbee2mqtt_gateway
    from alarm.gateways.zwavejs import default_zwavejs_gateway
    from alarm.rules.action_handlers import ActionContext, get_handler
    from alarm.rules.template_render import TriggerContext
    from alarm.state_machine import transitions as _transitions_module

    # Strip delay_seconds from the dispatched payload — otherwise the handler
    # would re-enqueue instead of executing.
    payload = copy.deepcopy(pa.action_payload)
    if isinstance(payload, dict):
        payload.pop("delay_seconds", None)

    action_type = payload.get("type") if isinstance(payload, dict) else None
    handler = get_handler(action_type) if isinstance(action_type, str) else None
    now = timezone.now()

    if handler is None:
        pa.status = PendingActionStatus.FAILED
        pa.fire_result = {"error": "unsupported_action", "type": str(action_type)}
        pa.fired_at = now
        pa.save(update_fields=["status", "fire_result", "fired_at", "updated_at"])
        return

    ctx = ActionContext(
        rule=pa.rule,
        actor_user=pa.actor_user,
        alarm_services=_transitions_module,
        ha=default_home_assistant_gateway,
        zwavejs=default_zwavejs_gateway,
        zigbee2mqtt=default_zigbee2mqtt_gateway,
        triggers=TriggerContext.empty(now),
        action_index=pa.action_index,
    )

    try:
        result, error = handler(payload, ctx)
        pa.fire_result = result
        pa.fired_at = now
        if error is None and result.get("ok", False):
            pa.status = PendingActionStatus.FIRED
        else:
            pa.status = PendingActionStatus.FAILED
        pa.save(update_fields=["status", "fire_result", "fired_at", "updated_at"])
    except Exception as exc:
        logger.warning("PendingAction %d handler raised: %s", pa.id, exc, exc_info=True)
        pa.status = PendingActionStatus.FAILED
        # The raw exception message can carry internal hostnames / connection
        # strings (e.g., DB or MQTT errors) and the list endpoint returns
        # fire_result to any authenticated user. Persist only the exception
        # class for the API surface; the full message + traceback are in logs.
        pa.fire_result = {"error": "handler_exception", "exception_class": type(exc).__name__}
        pa.fired_at = now
        pa.save(update_fields=["status", "fire_result", "fired_at", "updated_at"])


@register(
    "fire_due_pending_actions",
    schedule=Every(seconds=2),
    description="Fires queued rule actions whose delay has elapsed (ADR-0091).",
)
def fire_due_pending_actions() -> dict:
    """Pick up PendingAction rows whose ``fire_at`` has passed and dispatch them.

    Rows past the stale threshold are auto-cancelled instead of fired — keeps
    a long backend outage from suddenly emitting hours-old notifications.

    Returns ``{"fired": N, "failed": N, "stale_cancelled": N}``.
    """
    now = timezone.now()
    stale_cutoff = now - timedelta(seconds=PENDING_ACTION_STALE_THRESHOLD_SECONDS)

    # ADR-0094: capture stale-cancel candidates BEFORE the bulk update so we can
    # recover the alarm state for any cancelled alarm_trigger payloads — a
    # restart-during-PENDING scenario otherwise leaves the snapshot stuck in
    # PENDING with no scheduled follow-up.
    stale_alarm_trigger_rule_ids = list(
        PendingAction.objects.filter(
            status=PendingActionStatus.SCHEDULED,
            fire_at__lt=stale_cutoff,
            action_payload__type="alarm_trigger",
        ).values_list("id", flat=True)
    )

    # Auto-cancel rows that are too old to be useful (post-outage protection).
    stale_cancelled = PendingAction.objects.filter(
        status=PendingActionStatus.SCHEDULED,
        fire_at__lt=stale_cutoff,
    ).update(
        status=PendingActionStatus.CANCELLED,
        cancel_reason=PendingActionCancelReason.STALE_AFTER_RESTART,
        updated_at=now,
    )

    if stale_alarm_trigger_rule_ids:
        _recover_alarm_from_stale_pending_action(stale_alarm_trigger_rule_ids)

    fired = 0
    failed = 0

    # Pick up due rows. Cap the batch so a backlog doesn't block the tick.
    due_ids = list(
        PendingAction.objects.filter(
            status=PendingActionStatus.SCHEDULED,
            fire_at__lte=now,
        )
        .order_by("fire_at", "id")
        .values_list("id", flat=True)[:50]
    )

    for pa_id in due_ids:
        with transaction.atomic():
            try:
                pa = (
                    PendingAction.objects.select_for_update(skip_locked=True)
                    .filter(id=pa_id, status=PendingActionStatus.SCHEDULED)
                    .first()
                )
            except Exception as exc:
                logger.warning("Could not lock PendingAction %d: %s", pa_id, exc)
                continue
            if pa is None:
                continue  # Already fired/cancelled by a concurrent worker or signal.
            _fire_one_pending_action(pa)
            if pa.status == PendingActionStatus.FIRED:
                fired += 1
            elif pa.status == PendingActionStatus.FAILED:
                failed += 1

    if fired or failed or stale_cancelled:
        logger.info(
            "PendingAction tick: fired=%d failed=%d stale_cancelled=%d",
            fired,
            failed,
            stale_cancelled,
        )

    return {"fired": fired, "failed": failed, "stale_cancelled": stale_cancelled}
