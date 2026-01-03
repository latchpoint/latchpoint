from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from django.utils import timezone

from alarm.models import AlarmStateSnapshot, Entity, Rule, RuleRuntimeState
from alarm.rules.runtime_state import ensure_runtime


@dataclass(frozen=True)
class Detection:
    provider: str
    event_id: str
    label: str
    camera: str
    zones: list[str]
    confidence_pct: float
    observed_at: datetime


@dataclass(frozen=True)
class RuleEngineRepositories:
    list_enabled_rules: Callable[[], list[Rule]]
    entity_state_map: Callable[[], dict[str, str | None]]
    due_runtimes: Callable[[object], list[RuleRuntimeState]]
    ensure_runtime: Callable[[Rule], RuleRuntimeState]
    frigate_is_available: Callable[[object], bool]
    list_frigate_detections: Callable[[str, list[str], object], list[Detection]]
    get_alarm_state: Callable[[], str | None]


def default_rule_engine_repositories() -> RuleEngineRepositories:
    """Build the default repositories adapter used by the rules engine orchestration."""
    def _list_enabled_rules() -> list[Rule]:
        """Return enabled rules ordered by priority."""
        return list(Rule.objects.filter(enabled=True).order_by("-priority", "id"))

    def _entity_state_map() -> dict[str, str | None]:
        """Return a map of entity_id -> last_state for all entities."""
        return {e.entity_id: e.last_state for e in Entity.objects.all()}

    def _due_runtimes(now) -> list[RuleRuntimeState]:
        """Return runtimes due to execute by `now`, selecting for update."""
        now = now or timezone.now()
        return list(
            RuleRuntimeState.objects.select_for_update()
            .filter(scheduled_for__isnull=False, scheduled_for__lte=now, rule__enabled=True)
            .select_related("rule")
            .order_by("scheduled_for", "id")
        )

    def _frigate_is_available(now) -> bool:
        """Return True if Frigate appears available (best-effort)."""
        try:
            from integrations_frigate.runtime import is_available

            return bool(is_available(now=now))
        except Exception:
            return False

    def _list_frigate_detections(label: str, cameras: list[str], since) -> list[Detection]:
        """List normalized Frigate detections matching label/cameras and newer than `since`."""
        try:
            from integrations_frigate.models import FrigateDetection
        except Exception:
            return []
        if not isinstance(label, str) or not label.strip():
            return []
        if not isinstance(cameras, list) or not cameras:
            return []
        cleaned_cameras = [c.strip() for c in cameras if isinstance(c, str) and c.strip()]
        if not cleaned_cameras:
            return []
        if since is None:
            since = timezone.now() - timezone.timedelta(minutes=5)
        qs = (
            FrigateDetection.objects.filter(provider="frigate", label=label, camera__in=cleaned_cameras, observed_at__gte=since)
            .order_by("observed_at", "id")
            .only("provider", "event_id", "label", "camera", "zones", "confidence_pct", "observed_at")
        )
        return [
            Detection(
                provider=row.provider,
                event_id=row.event_id,
                label=row.label,
                camera=row.camera,
                zones=[str(z) for z in (row.zones or []) if isinstance(z, str) and str(z).strip()],
                confidence_pct=float(row.confidence_pct),
                observed_at=row.observed_at,
            )
            for row in qs
        ]

    def _get_alarm_state() -> str | None:
        """Return the current alarm state from the active snapshot, if any."""
        try:
            snapshot = (
                AlarmStateSnapshot.objects.filter(exit_at__isnull=True).order_by("-entered_at", "-id").first()
            )
            return snapshot.current_state if snapshot else None
        except Exception:
            return None

    return RuleEngineRepositories(
        list_enabled_rules=_list_enabled_rules,
        entity_state_map=_entity_state_map,
        due_runtimes=_due_runtimes,
        ensure_runtime=ensure_runtime,
        frigate_is_available=_frigate_is_available,
        list_frigate_detections=_list_frigate_detections,
        get_alarm_state=_get_alarm_state,
    )
