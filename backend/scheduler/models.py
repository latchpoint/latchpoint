from __future__ import annotations

from django.db import models


class SchedulerTaskRunStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    FAILURE = "failure", "Failure"
    SKIPPED = "skipped", "Skipped"
    TIMEOUT = "timeout", "Timeout"


class SchedulerTaskHealth(models.Model):
    """
    Latest per-task health snapshot, per running instance.

    This is optimized for frequent reads by the UI/API.
    """

    task_name = models.CharField(max_length=128)
    instance_id = models.CharField(max_length=128)

    enabled = models.BooleanField(default=True)
    schedule_type = models.CharField(max_length=32, blank=True)
    schedule_payload = models.JSONField(default=dict, blank=True)
    max_runtime_seconds = models.PositiveIntegerField(null=True, blank=True)

    next_run_at = models.DateTimeField(null=True, blank=True)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_finished_at = models.DateTimeField(null=True, blank=True)
    last_duration_seconds = models.FloatField(null=True, blank=True)

    is_running = models.BooleanField(default=False)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_error_message = models.TextField(blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task_name", "instance_id"],
                name="scheduler_task_health_unique_task_instance",
            )
        ]
        indexes = [
            models.Index(fields=["task_name", "instance_id"]),
            models.Index(fields=["instance_id"]),
            models.Index(fields=["task_name"]),
            models.Index(fields=["is_running"]),
            models.Index(fields=["consecutive_failures"]),
            models.Index(fields=["updated_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.instance_id}:{self.task_name}"


class SchedulerTaskRun(models.Model):
    """Append-only run history for debugging and incident review."""

    task_name = models.CharField(max_length=128)
    instance_id = models.CharField(max_length=128)

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=SchedulerTaskRunStatus.choices)
    duration_seconds = models.FloatField(null=True, blank=True)

    error_message = models.TextField(blank=True)
    error_traceback = models.TextField(blank=True)
    consecutive_failures_at_start = models.PositiveIntegerField(default=0)
    thread_name = models.CharField(max_length=128, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["task_name", "-started_at"]),
            models.Index(fields=["instance_id", "-started_at"]),
            models.Index(fields=["status", "-started_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.instance_id}:{self.task_name}:{self.status}:{self.started_at.isoformat()}"

