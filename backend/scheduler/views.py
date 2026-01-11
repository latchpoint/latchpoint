from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from config.pagination import EnvelopePagination
from scheduler.registry import get_tasks
from scheduler.runner import get_scheduler_status
from scheduler.runner import _compute_next_run

from .models import SchedulerTaskHealth, SchedulerTaskRun
from .telemetry import serialize_schedule
from .telemetry import get_instance_id


def _to_iso(dt):
    return dt.isoformat() if dt else None


def _humanize_task_name(task_name: str) -> str:
    value = (task_name or "").strip().replace("-", "_").replace("__", "_")
    words = [w for w in value.split("_") if w]
    titled = " ".join(w.capitalize() for w in words) if words else task_name

    replacements = {
        "Mqtt": "MQTT",
        "Zwavejs": "Z-Wave JS",
        "Zigbee2mqtt": "Zigbee2MQTT",
        "Frigate": "Frigate",
        "Ha": "HA",
        "Ws": "WS",
        "Id": "ID",
    }

    for src, dst in replacements.items():
        titled = titled.replace(src, dst)

    titled = titled.replace("Home Assistant", "Home Assistant")
    return titled


class SchedulerStatusView(APIView):
    """GET /api/scheduler/status/ - Scheduler status + per-task health (admin-only)."""

    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        instance_id = request.query_params.get("instance_id") or get_instance_id()

        now = timezone.now()

        tasks_by_name = get_tasks()
        health_by_task_name = {
            row.task_name: row
            for row in SchedulerTaskHealth.objects.filter(instance_id=instance_id)
        }

        tasks = []
        registered_task_names = set(tasks_by_name.keys())

        for task_name in sorted(registered_task_names):
            task = tasks_by_name[task_name]
            schedule_type, schedule_payload = serialize_schedule(task)
            display_name = _humanize_task_name(task_name)
            description = task.description

            row = health_by_task_name.get(task_name)
            observed = row is not None

            enabled = bool(task.enabled)
            max_runtime_seconds = task.max_runtime_seconds

            next_run_at = None
            last_started_at = None
            last_finished_at = None
            last_duration_seconds = None
            is_running = False
            consecutive_failures = 0
            last_error_message = None
            last_heartbeat_at = None

            if row is not None:
                next_run_at = row.next_run_at
                last_started_at = row.last_started_at
                last_finished_at = row.last_finished_at
                last_duration_seconds = row.last_duration_seconds
                is_running = bool(row.is_running)
                consecutive_failures = int(row.consecutive_failures or 0)
                last_error_message = row.last_error_message or None
                last_heartbeat_at = row.last_heartbeat_at
                if row.max_runtime_seconds is not None:
                    max_runtime_seconds = row.max_runtime_seconds
            else:
                try:
                    next_run_at = _compute_next_run(task.schedule, now)
                except Exception:
                    next_run_at = None

            is_stuck = False
            stuck_for_seconds = None
            if is_running and max_runtime_seconds and last_started_at:
                runtime = (now - last_started_at).total_seconds()
                if runtime > float(max_runtime_seconds):
                    is_stuck = True
                    stuck_for_seconds = int(runtime)

            derived_status = "ok"
            if not enabled:
                derived_status = "disabled"
            elif is_stuck:
                derived_status = "stuck"
            elif is_running:
                derived_status = "running"
            elif consecutive_failures > 0:
                derived_status = "failing"
            elif not observed:
                derived_status = "never_ran"

            tasks.append(
                {
                    "task_name": task_name,
                    "display_name": display_name,
                    "description": description,
                    "instance_id": instance_id,
                    "observed": observed,
                    "enabled": enabled,
                    "schedule_type": schedule_type,
                    "schedule_payload": schedule_payload,
                    "max_runtime_seconds": max_runtime_seconds,
                    "next_run_at": _to_iso(next_run_at),
                    "last_started_at": _to_iso(last_started_at),
                    "last_finished_at": _to_iso(last_finished_at),
                    "last_duration_seconds": last_duration_seconds,
                    "is_running": is_running,
                    "consecutive_failures": consecutive_failures,
                    "last_error_message": last_error_message,
                    "last_heartbeat_at": _to_iso(last_heartbeat_at),
                    "status": derived_status,
                    "stuck_for_seconds": stuck_for_seconds,
                }
            )

        # Include persisted health for tasks not registered in this process (e.g. removed/renamed).
        orphaned_task_names = sorted(set(health_by_task_name.keys()) - registered_task_names)
        for task_name in orphaned_task_names:
            row = health_by_task_name[task_name]
            display_name = _humanize_task_name(task_name)

            is_stuck = False
            stuck_for_seconds = None
            if row.is_running and row.max_runtime_seconds and row.last_started_at:
                runtime = (now - row.last_started_at).total_seconds()
                if runtime > float(row.max_runtime_seconds):
                    is_stuck = True
                    stuck_for_seconds = int(runtime)

            derived_status = "orphaned"
            if not row.enabled:
                derived_status = "disabled"
            elif is_stuck:
                derived_status = "stuck"
            elif row.is_running:
                derived_status = "running"
            elif row.consecutive_failures > 0:
                derived_status = "failing"

            tasks.append(
                {
                    "task_name": row.task_name,
                    "display_name": display_name,
                    "description": None,
                    "instance_id": row.instance_id,
                    "observed": True,
                    "enabled": bool(row.enabled),
                    "schedule_type": row.schedule_type,
                    "schedule_payload": row.schedule_payload,
                    "max_runtime_seconds": row.max_runtime_seconds,
                    "next_run_at": _to_iso(row.next_run_at),
                    "last_started_at": _to_iso(row.last_started_at),
                    "last_finished_at": _to_iso(row.last_finished_at),
                    "last_duration_seconds": row.last_duration_seconds,
                    "is_running": bool(row.is_running),
                    "consecutive_failures": int(row.consecutive_failures or 0),
                    "last_error_message": row.last_error_message or None,
                    "last_heartbeat_at": _to_iso(row.last_heartbeat_at),
                    "status": derived_status,
                    "stuck_for_seconds": stuck_for_seconds,
                }
            )

        return Response(
            {
                "instance_id": instance_id,
                "runtime": get_scheduler_status(),
                "tasks": tasks,
            },
            status=status.HTTP_200_OK,
        )


class SchedulerTaskRunsView(GenericAPIView):
    """GET /api/scheduler/tasks/<task_name>/runs/ - Paginated run history (admin-only)."""

    permission_classes = [IsAuthenticated, IsAdminRole]
    pagination_class = EnvelopePagination

    def get(self, request, task_name: str):
        qs = SchedulerTaskRun.objects.filter(task_name=task_name).order_by("-started_at")

        instance_id = request.query_params.get("instance_id")
        if instance_id:
            qs = qs.filter(instance_id=instance_id)

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        since = request.query_params.get("since")
        if since:
            try:
                since_dt = datetime.fromisoformat(since)
                if timezone.is_naive(since_dt):
                    since_dt = timezone.make_aware(since_dt)
                qs = qs.filter(started_at__gte=since_dt)
            except Exception:
                pass

        page = self.paginate_queryset(qs)
        if page is None:
            page = list(qs)
        results = []
        for row in page:
            results.append(
                {
                    "id": row.id,
                    "task_name": row.task_name,
                    "instance_id": row.instance_id,
                    "started_at": _to_iso(row.started_at),
                    "finished_at": _to_iso(row.finished_at),
                    "status": row.status,
                    "duration_seconds": row.duration_seconds,
                    "error_message": row.error_message or None,
                    "consecutive_failures_at_start": row.consecutive_failures_at_start,
                    "thread_name": row.thread_name,
                    "created_at": _to_iso(row.created_at),
                }
            )
        return self.get_paginated_response(results)
