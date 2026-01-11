from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from scheduler.registry import register
from scheduler.schedules import DailyAt

from .models import SchedulerTaskRun


@register(
    "scheduler_cleanup_task_runs",
    schedule=DailyAt(hour=3, minute=15),
    description="Cleans up old scheduler history so it doesn’t grow without limits.",
)
def scheduler_cleanup_task_runs() -> None:
    retention_days = int(getattr(settings, "SCHEDULER_RUN_HISTORY_RETENTION_DAYS", 30))
    max_per_task = int(getattr(settings, "SCHEDULER_RUN_HISTORY_MAX_PER_TASK", 500))

    now = timezone.now()
    if retention_days > 0:
        cutoff = now - timedelta(days=retention_days)
        SchedulerTaskRun.objects.filter(started_at__lt=cutoff).delete()

    if max_per_task <= 0:
        return

    task_names = (
        SchedulerTaskRun.objects.values_list("task_name", flat=True)
        .distinct()
        .order_by("task_name")
    )

    for task_name in task_names:
        keep_ids = list(
            SchedulerTaskRun.objects.filter(task_name=task_name)
            .order_by("-started_at")
            .values_list("id", flat=True)[:max_per_task]
        )
        if not keep_ids:
            continue
        SchedulerTaskRun.objects.filter(task_name=task_name).exclude(id__in=keep_ids).delete()
