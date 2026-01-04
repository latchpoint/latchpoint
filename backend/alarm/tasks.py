"""Background tasks for the alarm app."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

from alarm.models import AlarmEvent, Entity, RuleActionLog, RuleEntityRef, SystemConfig
from alarm.settings_registry import SYSTEM_CONFIG_SETTINGS_BY_KEY
from scheduler import DailyAt, Every, register

logger = logging.getLogger(__name__)


def _get_retention_days() -> int:
    """Read events.retention_days from SystemConfig, fallback to default."""
    default = SYSTEM_CONFIG_SETTINGS_BY_KEY["events.retention_days"].default

    try:
        config = SystemConfig.objects.get(key="events.retention_days")
        return int(config.value)
    except SystemConfig.DoesNotExist:
        return default
    except (TypeError, ValueError):
        logger.warning("Invalid events.retention_days value, using default %d", default)
        return default


@register("cleanup_old_events", schedule=DailyAt(hour=3, minute=0))
def cleanup_old_events() -> int:
    """
    Delete AlarmEvent records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_retention_days()
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
    default = SYSTEM_CONFIG_SETTINGS_BY_KEY["rule_logs.retention_days"].default

    try:
        config = SystemConfig.objects.get(key="rule_logs.retention_days")
        return int(config.value)
    except SystemConfig.DoesNotExist:
        return default
    except (TypeError, ValueError):
        logger.warning(
            "Invalid rule_logs.retention_days value, using default %d", default
        )
        return default


@register("cleanup_rule_action_logs", schedule=DailyAt(hour=3, minute=30))
def cleanup_rule_action_logs() -> int:
    """
    Delete RuleActionLog records older than the configured retention period.

    Returns the count of deleted records.
    """
    retention_days = _get_rule_log_retention_days()
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


@register("cleanup_expired_sessions", schedule=DailyAt(hour=4, minute=0))
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
    default = SYSTEM_CONFIG_SETTINGS_BY_KEY["entity_sync.interval_seconds"].default

    try:
        config = SystemConfig.objects.get(key="entity_sync.interval_seconds")
        return int(config.value)
    except SystemConfig.DoesNotExist:
        return default
    except (TypeError, ValueError):
        logger.warning(
            "Invalid entity_sync.interval_seconds value, using default %d", default
        )
        return default


@register("sync_entity_states", schedule=Every(seconds=300, jitter=30))
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
            changed_entities.append({
                "entity_id": entity.entity_id,
                "old_state": old_state,
                "new_state": new_state,
            })

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
            notify_entities_changed(source="home_assistant", entity_ids=changed_entity_ids)
        except Exception as e:
            logger.debug("Dispatcher notification skipped: %s", e)

    return {"synced": synced, "updated": updated, "errors": 0}


@register("broadcast_system_status", schedule=Every(seconds=2))
def broadcast_system_status() -> None:
    """Broadcast integration status to websocket clients (local integrations)."""
    from alarm.system_status import recompute_and_broadcast_system_status

    recompute_and_broadcast_system_status(include_home_assistant=False)


@register("check_home_assistant", schedule=Every(seconds=30, jitter=5))
def check_home_assistant() -> None:
    """Check Home Assistant status and broadcast if changed."""
    from alarm.system_status import recompute_and_broadcast_system_status

    recompute_and_broadcast_system_status(include_home_assistant=True)


@register("process_due_rule_runtimes", schedule=Every(seconds=5, jitter=1))
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


@register("cleanup_orphan_rule_entity_refs", schedule=DailyAt(hour=4, minute=30))
def cleanup_orphan_rule_entity_refs() -> int:
    """
    Remove RuleEntityRef rows pointing to non-existent entities.

    Weekly cleanup for stale references as part of ADR 0057.

    Returns the count of deleted records.
    """
    # Find refs where entity no longer exists
    # Using a subquery to find orphaned refs
    existing_entity_ids = Entity.objects.values_list("id", flat=True)
    orphan_refs = RuleEntityRef.objects.exclude(entity_id__in=existing_entity_ids)

    count = orphan_refs.count()
    if count > 0:
        orphan_refs.delete()
        logger.info("Cleaned up %d orphan RuleEntityRef rows", count)

    return count
