from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q


class AlarmState(models.TextChoices):
    DISARMED = "disarmed", "Disarmed"
    ARMING = "arming", "Arming"
    ARMED_HOME = "armed_home", "Armed home"
    ARMED_AWAY = "armed_away", "Armed away"
    ARMED_NIGHT = "armed_night", "Armed night"
    ARMED_VACATION = "armed_vacation", "Armed vacation"
    PENDING = "pending", "Pending"
    TRIGGERED = "triggered", "Triggered"


class AlarmEventType(models.TextChoices):
    ARMED = "armed", "Armed"
    DISARMED = "disarmed", "Disarmed"
    PENDING = "pending", "Pending"
    TRIGGERED = "triggered", "Triggered"
    CODE_USED = "code_used", "Code used"
    SENSOR_TRIGGERED = "sensor_triggered", "Sensor triggered"
    FAILED_CODE = "failed_code", "Failed code"
    STATE_CHANGED = "state_changed", "State changed"
    INTEGRATION_OFFLINE = "integration_offline", "Integration offline"
    INTEGRATION_RECOVERED = "integration_recovered", "Integration recovered"
    SCHEDULER_TASK_FAILED = "scheduler_task_failed", "Scheduler task failed"
    SCHEDULER_TASK_STUCK = "scheduler_task_stuck", "Scheduler task stuck"


class SystemConfigValueType(models.TextChoices):
    BOOLEAN = "boolean", "Boolean"
    INTEGER = "integer", "Integer"
    FLOAT = "float", "Float"
    STRING = "string", "String"
    JSON = "json", "JSON"


class AlarmSystem(models.Model):
    name = models.CharField(max_length=150)
    timezone = models.CharField(max_length=64, default=settings.TIME_ZONE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a human-friendly identifier for logs/admin lists."""
        return self.name


class AlarmSettingsProfile(models.Model):
    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a human-friendly identifier for logs/admin lists."""
        return self.name


class AlarmStateSnapshot(models.Model):
    current_state = models.CharField(max_length=32, choices=AlarmState.choices)
    previous_state = models.CharField(
        max_length=32, choices=AlarmState.choices, null=True, blank=True
    )
    target_armed_state = models.CharField(
        max_length=32, choices=AlarmState.choices, null=True, blank=True
    )
    settings_profile = models.ForeignKey(
        AlarmSettingsProfile,
        on_delete=models.PROTECT,
        related_name="state_snapshots",
    )
    entered_at = models.DateTimeField()
    exit_at = models.DateTimeField(null=True, blank=True)
    last_transition_reason = models.CharField(max_length=64, blank=True)
    last_transition_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alarm_transitions",
    )
    timing_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["current_state"]),
            models.Index(fields=["exit_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.current_state} ({self.entered_at})"


class AlarmSettingsEntry(models.Model):
    profile = models.ForeignKey(
        AlarmSettingsProfile,
        on_delete=models.CASCADE,
        related_name="entries",
    )
    key = models.CharField(max_length=128)
    value_type = models.CharField(max_length=16, choices=SystemConfigValueType.choices)
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "key"], name="alarm_settings_entries_unique_profile_key"),
        ]
        indexes = [
            models.Index(fields=["profile", "key"]),
            models.Index(fields=["key"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.profile_id}:{self.key}"


class Sensor(models.Model):
    name = models.CharField(max_length=150)
    entity_id = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    is_entry_point = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a human-friendly identifier for logs/admin lists."""
        return self.name


class AlarmEvent(models.Model):
    event_type = models.CharField(max_length=32, choices=AlarmEventType.choices)
    state_from = models.CharField(
        max_length=32, choices=AlarmState.choices, null=True, blank=True
    )
    state_to = models.CharField(
        max_length=32, choices=AlarmState.choices, null=True, blank=True
    )
    timestamp = models.DateTimeField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alarm_events",
    )
    code = models.ForeignKey(
        "accounts.UserCode",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alarm_events",
    )
    sensor = models.ForeignKey(
        Sensor,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alarm_events",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "timestamp"]),
            models.Index(fields=["state_to"]),
            models.Index(fields=["timestamp"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(timestamp__isnull=False),
                name="alarm_events_timestamp_not_null",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.event_type}:{self.timestamp}"


class EntityTag(models.Model):
    name = models.CharField(max_length=64, unique=True)
    color = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a human-friendly identifier for logs/admin lists."""
        return self.name


class Entity(models.Model):
    entity_id = models.CharField(max_length=255, unique=True)
    domain = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=255)
    device_class = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    last_state = models.CharField(max_length=255, null=True, blank=True)
    last_changed = models.DateTimeField(null=True, blank=True, db_index=True)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    attributes = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=64, blank=True)
    tags = models.ManyToManyField(EntityTag, related_name="entities", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["domain"]),
        ]
        ordering = ["entity_id"]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a stable identifier for logs/admin lists."""
        return self.entity_id


class RuleKind(models.TextChoices):
    TRIGGER = "trigger", "Trigger"
    DISARM = "disarm", "Disarm"
    ARM = "arm", "Arm"
    SUPPRESS = "suppress", "Suppress"
    ESCALATE = "escalate", "Escalate"


class Rule(models.Model):
    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=32, choices=RuleKind.choices, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)
    priority = models.IntegerField(default=0, db_index=True)
    schema_version = models.PositiveIntegerField(default=1)
    definition = models.JSONField(default=dict, blank=True)
    cooldown_seconds = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alarm_rules_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["enabled", "kind", "-priority"]),
        ]
        ordering = ["-priority", "id"]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.kind}:{self.name}"


class RuleEntityRef(models.Model):
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="entity_refs")
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="rule_refs")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["rule", "entity"], name="rule_entity_ref_unique"),
        ]
        indexes = [
            models.Index(fields=["entity", "rule"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.rule_id}:{self.entity_id}"


class RuleRuntimeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SATISFIED = "satisfied", "Satisfied"
    COOLDOWN = "cooldown", "Cooldown"
    ERROR_SUSPENDED = "error_suspended", "Error Suspended"


class RuleRuntimeState(models.Model):
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="runtime_states")
    node_id = models.CharField(max_length=128)
    status = models.CharField(
        max_length=32, choices=RuleRuntimeStatus.choices, default=RuleRuntimeStatus.PENDING
    )
    became_true_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True, db_index=True)
    last_when_matched = models.BooleanField(null=True, blank=True)
    last_when_transition_at = models.DateTimeField(null=True, blank=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    fingerprint = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Failure tracking for circuit breaker (ADR 0057)
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    next_allowed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    error_suspended = models.BooleanField(default=False, db_index=True)
    last_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["rule", "node_id"], name="rule_node_unique"),
        ]
        indexes = [
            models.Index(fields=["rule", "node_id"]),
            models.Index(fields=["error_suspended"]),
            models.Index(fields=["next_allowed_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.rule_id}:{self.node_id}"


class RuleActionLog(models.Model):
    rule = models.ForeignKey(Rule, null=True, blank=True, on_delete=models.SET_NULL)
    entity = models.ForeignKey(Entity, null=True, blank=True, on_delete=models.SET_NULL)
    fired_at = models.DateTimeField()
    kind = models.CharField(max_length=32, choices=RuleKind.choices, blank=True)
    actions = models.JSONField(default=list, blank=True)
    result = models.JSONField(default=dict, blank=True)
    trace = models.JSONField(default=dict, blank=True)
    alarm_state_before = models.CharField(max_length=32, blank=True)
    alarm_state_after = models.CharField(max_length=32, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["fired_at"]),
            models.Index(fields=["kind", "fired_at"]),
        ]
        ordering = ["-fired_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.fired_at}:{self.kind}"


class SystemConfig(models.Model):
    key = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=150)
    value_type = models.CharField(max_length=16, choices=SystemConfigValueType.choices)
    value = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="system_config_modified",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]
        indexes = [
            models.Index(fields=["key"]),
            models.Index(fields=["value_type"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a stable identifier for logs/admin lists."""
        return self.key
