from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from accounts.models import User

class DoorCode(models.Model):
    """Door lock access code."""

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        SYNCED = "synced", "Synced"

    class CodeType(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        TEMPORARY = "temporary", "Temporary"
        ONE_TIME = "one_time", "One-time"
        SERVICE = "service", "Service"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="door_codes")
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    code_hash = models.TextField(null=True, blank=True)
    label = models.CharField(max_length=150, blank=True)
    code_type = models.CharField(max_length=16, choices=CodeType.choices)
    pin_length = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(4), MaxValueValidator(8)],
    )
    is_active = models.BooleanField(default=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    uses_count = models.PositiveIntegerField(default=0)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    days_of_week = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(127)]
    )
    window_start = models.TimeField(null=True, blank=True)
    window_end = models.TimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_lock = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "door_codes"
        indexes = [
            models.Index(fields=["user"]),
            models.Index(
                fields=["user"],
                condition=Q(is_active=True),
                name="door_codes_active_user_idx",
            ),
            models.Index(
                fields=["end_at"],
                condition=Q(end_at__isnull=False),
                name="door_codes_end_at_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(pin_length__gte=4) & Q(pin_length__lte=8),
                name="door_codes_pin_length_between_4_8",
            ),
            models.CheckConstraint(
                condition=Q(days_of_week__isnull=True)
                | (Q(days_of_week__gte=0) & Q(days_of_week__lte=127)),
                name="door_codes_days_of_week_between_0_127",
            ),
            models.CheckConstraint(
                condition=Q(uses_count__gte=0),
                name="door_codes_uses_count_gte_0",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.user_id}:{self.label or self.id}"


class DoorCodeLockAssignment(models.Model):
    """Assignment of door codes to specific locks."""

    id = models.BigAutoField(primary_key=True)
    door_code = models.ForeignKey(
        DoorCode, on_delete=models.CASCADE, related_name="lock_assignments"
    )
    lock_entity_id = models.CharField(max_length=255)
    slot_index = models.PositiveSmallIntegerField(null=True, blank=True)
    sync_dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "door_code_lock_assignments"
        constraints = [
            models.UniqueConstraint(
                fields=["door_code", "lock_entity_id"],
                name="door_code_lock_assignments_unique_code_lock",
            ),
            models.UniqueConstraint(
                fields=["lock_entity_id", "slot_index"],
                condition=Q(slot_index__isnull=False),
                name="door_code_lock_assignments_unique_lock_slot",
            ),
        ]
        indexes = [
            models.Index(fields=["lock_entity_id"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.door_code_id}:{self.lock_entity_id}"


class DoorCodeEvent(models.Model):
    """Audit log for door code operations."""

    class EventType(models.TextChoices):
        CODE_USED = "code_used", "Code Used"
        CODE_FAILED = "code_failed", "Code Failed"
        CODE_SYNCED = "code_synced", "Code Synced"
        CODE_REMOVED = "code_removed", "Code Removed"
        CODE_CREATED = "code_created", "Code Created"
        CODE_UPDATED = "code_updated", "Code Updated"
        CODE_DELETED = "code_deleted", "Code Deleted"

    id = models.BigAutoField(primary_key=True)
    door_code = models.ForeignKey(
        DoorCode,
        on_delete=models.CASCADE,
        related_name="events",
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="door_code_events",
    )
    lock_entity_id = models.CharField(max_length=255, blank=True)
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "door_code_events"
        indexes = [
            models.Index(fields=["door_code", "created_at"]),
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - simple representation
        """Return a compact representation for logs/admin lists."""
        return f"{self.event_type}:{self.door_code_id or 'N/A'}"
